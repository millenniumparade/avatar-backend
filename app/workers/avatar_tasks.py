"""Avatar generation worker tasks."""

from __future__ import annotations

import shutil
import tempfile
from uuid import uuid4
from pathlib import Path

from celery import signals
from celery.exceptions import SoftTimeLimitExceeded

from app.algorithms.pipeline import generate_cartoon_avatar, preload_models
from app.algorithms.types import PipelineConfig, PipelineResult
from app.core.config import settings
from app.core.errors import AvatarError, ErrorCode
from app.db.session import SessionLocal
from app.models.avatar_job import AvatarJobStage, AvatarJobStatus
from app.models.avatar_result import AvatarResult
from app.repositories.avatar_artifact_repository import AvatarArtifactRepository
from app.repositories.avatar_job_repository import AvatarJobRepository
from app.repositories.avatar_result_repository import AvatarResultRepository
from app.repositories.outbox_event_repository import OutboxEventRepository
from app.services.rate_limit_service import RateLimitService
from app.services.storage_service import StorageService
from app.workers.celery_app import celery_app

MODEL_REGISTRY: dict[str, object] = {}
RATE_LIMIT_SERVICE_FACTORY = RateLimitService


def initialize_worker_models() -> None:
    """Load model handles once per worker process."""

    global MODEL_REGISTRY
    try:
        MODEL_REGISTRY = preload_models()
    except NotImplementedError:
        MODEL_REGISTRY = {}


@signals.worker_process_init.connect
def _on_worker_process_init(**_: object) -> None:
    initialize_worker_models()


@celery_app.task(name="avatar.process_job", bind=True, max_retries=1)
def process_avatar_job(self, job_id: str) -> None:
    """Process one avatar generation job and persist its result."""

    worker_id = str(getattr(self.request, "hostname", "") or "worker")
    task_id = str(getattr(self.request, "id", "") or "")
    session = SessionLocal()
    storage = StorageService()
    work_dir: str | None = None
    input_image_path: str | None = None

    try:
        job_repo = AvatarJobRepository(session)
        result_repo = AvatarResultRepository(session)
        artifact_repo = AvatarArtifactRepository(session)

        job = job_repo.get_by_id(job_id)
        if job is None:
            return
        if job.status == AvatarJobStatus.CANCELLED:
            return
        if job.image is None:
            _mark_failed(session, job_id, ErrorCode.NOT_FOUND, "Uploaded image for this job was not found.")
            return
        if not job_repo.claim_for_processing(job_id, celery_task_id=task_id, worker_id=worker_id):
            session.rollback()
            return
        session.commit()

        input_image_path = _run_async(storage.get_local_path(job.image.original_image_key))
        work_dir = tempfile.mkdtemp(prefix=f"avatar-{job.id}-")
        config = PipelineConfig(
            algorithm_version=settings.algorithm_version,
            asset_library_version=settings.asset_library_version,
            timeout_seconds=settings.job_timeout_seconds,
        )
        result = _run_pipeline_with_heartbeat(
            job_repo=job_repo,
            job_id=job_id,
            worker_id=worker_id,
            input_image_path=input_image_path,
            work_dir=work_dir,
            config=config,
        )

        job_repo.touch_heartbeat(
            job_id,
            progress=90,
            stage=AvatarJobStage.RESULT_BUILDING,
            worker_id=worker_id,
        )
        result_json_key = storage.build_result_json_key(user_id=str(job.user_id), job_id=str(job.id))
        _run_async(storage.save_json(result_json_key, result.human_info))
        preview_key = _save_optional_preview(storage, job, result)
        _save_artifacts(storage, artifact_repo, job, result)

        avatar_result = result_repo.create(
            AvatarResult(
                user_id=job.user_id,
                image_id=job.image_id,
                job_id=job.id,
                result_json=result.human_info,
                result_json_key=result_json_key,
                preview_image_key=preview_key,
                schema_version=settings.result_schema_version,
                algorithm_version=settings.algorithm_version,
                asset_library_version=settings.asset_library_version,
            )
        )
        job_repo.mark_succeeded(job.id, avatar_result.id)
        session.commit()
        _release_active_job_best_effort(str(job.user_id), str(job.id))
    except SoftTimeLimitExceeded:
        _mark_failed(session, job_id, ErrorCode.PROCESSING_TIMEOUT, "Avatar reconstruction timed out.", timeout=True)
    except AvatarError as exc:
        _mark_failed(session, job_id, exc.code, exc.message)
    except RuntimeError as exc:
        if _is_oom_error(exc):
            _mark_failed(
                session,
                job_id,
                ErrorCode.CUDA_OOM,
                "3DMM reconstruction exceeded available GPU or system memory.",
            )
        else:
            _mark_failed(session, job_id, ErrorCode.INTERNAL_ERROR, f"Worker failed: {exc}")
    except Exception as exc:
        _mark_failed(session, job_id, ErrorCode.INTERNAL_ERROR, f"Worker failed: {exc}")
    finally:
        session.close()
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        if input_image_path:
            Path(input_image_path).unlink(missing_ok=True)


@celery_app.task(name="avatar.expire_stale_jobs")
def expire_stale_jobs() -> int:
    """Watchdog task that moves heartbeat-stale jobs to timeout."""

    session = SessionLocal()
    try:
        jobs = AvatarJobRepository(session).expire_stale_processing(
            heartbeat_timeout_seconds=settings.job_heartbeat_timeout_seconds
        )
        session.commit()
        for job in jobs:
            _release_active_job_best_effort(str(job.user_id), str(job.id))
        return len(jobs)
    finally:
        session.close()


@celery_app.task(name="avatar.dispatch_outbox")
def dispatch_outbox() -> int:
    """Dispatch committed outbox events to Celery."""

    session = SessionLocal()
    dispatcher_id = f"dispatcher-{uuid4()}"
    dispatched_count = 0
    try:
        repo = OutboxEventRepository(session)
        events = repo.claim_pending(
            dispatcher_id=dispatcher_id,
            limit=settings.outbox_dispatch_batch_size,
            stale_after_seconds=settings.outbox_lock_timeout_seconds,
        )
        session.commit()

        for event in events:
            try:
                if event.event_type != "avatar.process_job":
                    raise ValueError(f"Unsupported outbox event type: {event.event_type}")
                payload = event.payload
                process_avatar_job.apply_async(
                    args=[payload["job_id"]],
                    queue=payload["queue"],
                    task_id=payload["task_id"],
                )
                repo.mark_sent(event)
                dispatched_count += 1
            except Exception as exc:
                repo.mark_failed(
                    event,
                    str(exc),
                    retry_delay_seconds=settings.outbox_retry_delay_seconds,
                )
            session.commit()
        return dispatched_count
    finally:
        session.close()


@celery_app.task(name="avatar.redispatch_stale_queued_jobs")
def redispatch_stale_queued_jobs() -> int:
    """Create outbox events for queued jobs whose dispatch path stalled."""

    session = SessionLocal()
    try:
        repo = AvatarJobRepository(session)
        stale_jobs = repo.find_stale_queued(
            queued_after_seconds=settings.queued_job_redispatch_after_seconds,
            limit=settings.outbox_dispatch_batch_size,
        )
        created = 0
        outbox_repo = OutboxEventRepository(session)
        for job in stale_jobs:
            if outbox_repo.has_open_avatar_job_event(job.id):
                continue
            task_id = job.celery_task_id or f"avatar-job-{job.id}"
            job.celery_task_id = task_id
            outbox_repo.create_avatar_job_event(
                job_id=job.id,
                task_id=task_id,
                queue=settings.celery_gpu_queue,
            )
            created += 1
        session.commit()
        return created
    finally:
        session.close()


def _run_pipeline_with_heartbeat(
    *,
    job_repo: AvatarJobRepository,
    job_id: str,
    worker_id: str,
    input_image_path: str,
    work_dir: str,
    config: PipelineConfig,
) -> PipelineResult:
    job_repo.touch_heartbeat(
        job_id,
        progress=20,
        stage=AvatarJobStage.FACEVERSE_RECONSTRUCTION,
        worker_id=worker_id,
    )
    job_repo.session.commit()
    return generate_cartoon_avatar(
        input_image_path=input_image_path,
        work_dir=work_dir,
        config=config,
        models=MODEL_REGISTRY,
    )


def _save_optional_preview(storage: StorageService, job, result: PipelineResult) -> str | None:
    if not result.preview_image_path:
        return None
    source = Path(result.preview_image_path)
    if not source.exists():
        return None
    key = storage.build_artifact_key(user_id=str(job.user_id), job_id=str(job.id), filename="preview.jpg")
    with source.open("rb") as input_file:
        _run_async(storage.save_stream(key, input_file))
    return key


def _save_artifacts(storage: StorageService, artifact_repo: AvatarArtifactRepository, job, result: PipelineResult) -> None:
    for artifact_type, artifact_path in result.artifact_paths.items():
        source = Path(artifact_path)
        if not source.exists():
            continue
        key = storage.build_artifact_key(user_id=str(job.user_id), job_id=str(job.id), filename=source.name)
        with source.open("rb") as input_file:
            _run_async(storage.save_stream(key, input_file))
        from app.models.avatar_artifact import AvatarArtifact

        artifact_repo.create(
            AvatarArtifact(
                job_id=job.id,
                artifact_type=artifact_type,
                object_key=key,
                metadata_json={"timing": result.timing.get(artifact_type)},
            )
        )


def _mark_failed(
    session,
    job_id: str,
    error_code: ErrorCode,
    error_message: str,
    *,
    timeout: bool = False,
) -> None:
    status = AvatarJobStatus.TIMEOUT if timeout else AvatarJobStatus.FAILED
    job = AvatarJobRepository(session).mark_failed(job_id, error_code.value, error_message, status=status)
    session.commit()
    if job is not None:
        _release_active_job_best_effort(str(job.user_id), str(job.id))


def _release_active_job_best_effort(user_id: str, job_id: str | None = None) -> None:
    RATE_LIMIT_SERVICE_FACTORY().release_active_job_best_effort(user_id, job_id=job_id)


def _is_oom_error(exc: RuntimeError) -> bool:
    message = str(exc).lower()
    return "out of memory" in message or "cuda oom" in message or "cuda error: out of memory" in message


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)
