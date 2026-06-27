from __future__ import annotations

from uuid import uuid4

from app.algorithms.types import PipelineResult
from app.core.errors import ErrorCode
from app.models.avatar_job import AvatarJob, AvatarJobStatus
from app.models.outbox_event import OutboxEvent, OutboxEventStatus
import app.workers.avatar_tasks as avatar_tasks
from app.workers.avatar_tasks import _is_oom_error, _mark_failed
from app.repositories.avatar_job_repository import AvatarJobRepository
from app.repositories.outbox_event_repository import OutboxEventRepository
from app.services.rate_limit_service import RateLimitService
from tests.fakes import FailingRedis, FakeRedis
from sqlalchemy.orm import sessionmaker


def test_runtime_cuda_oom_detection() -> None:
    assert _is_oom_error(RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")) is True
    assert _is_oom_error(RuntimeError("some unrelated runtime failure")) is False


def test_mark_failed_can_record_timeout(session) -> None:
    from app.repositories.uploaded_image_repository import UploadedImageRepository
    from app.models.user import User

    user = User(device_id=f"device-{uuid4()}")
    session.add(user)
    session.flush()
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-1",
        original_image_key="original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    job = AvatarJob(
        user_id=user.id,
        image_id=image.id,
        status=AvatarJobStatus.PROCESSING,
        progress=40,
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        schema_version="1.0",
    )
    session.add(job)
    session.flush()

    avatar_tasks.RATE_LIMIT_SERVICE_FACTORY = lambda: RateLimitService(FakeRedis())
    try:
        _mark_failed(session, str(job.id), ErrorCode.PROCESSING_TIMEOUT, "timed out", timeout=True)
    finally:
        avatar_tasks.RATE_LIMIT_SERVICE_FACTORY = RateLimitService

    assert job.status == AvatarJobStatus.TIMEOUT
    assert job.error_code == ErrorCode.PROCESSING_TIMEOUT


def test_mark_failed_does_not_raise_when_redis_release_times_out(session) -> None:
    from app.repositories.uploaded_image_repository import UploadedImageRepository
    from app.models.user import User

    user = User(device_id=f"device-{uuid4()}")
    session.add(user)
    session.flush()
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-release-timeout",
        original_image_key="original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    job = AvatarJob(
        user_id=user.id,
        image_id=image.id,
        status=AvatarJobStatus.PROCESSING,
        progress=40,
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        schema_version="1.0",
    )
    session.add(job)
    session.flush()

    avatar_tasks.RATE_LIMIT_SERVICE_FACTORY = lambda: RateLimitService(
        FailingRedis(fail_on={"delete", "decr"})
    )
    try:
        _mark_failed(session, str(job.id), ErrorCode.INTERNAL_ERROR, "failed")
    finally:
        avatar_tasks.RATE_LIMIT_SERVICE_FACTORY = RateLimitService

    assert job.status == AvatarJobStatus.FAILED
    assert job.error_code == ErrorCode.INTERNAL_ERROR


def test_claim_for_processing_is_idempotent(session) -> None:
    from app.repositories.uploaded_image_repository import UploadedImageRepository
    from app.models.user import User

    user = User(device_id=f"device-{uuid4()}")
    session.add(user)
    session.flush()
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-claim",
        original_image_key="original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    job = AvatarJob(
        user_id=user.id,
        image_id=image.id,
        status=AvatarJobStatus.QUEUED,
        progress=0,
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        schema_version="1.0",
    )
    session.add(job)
    session.commit()

    repo = AvatarJobRepository(session)

    assert repo.claim_for_processing(job.id, celery_task_id="task-1", worker_id="worker-1") is True
    assert repo.claim_for_processing(job.id, celery_task_id="task-1", worker_id="worker-1") is False


def test_duplicate_worker_delivery_does_not_run_pipeline(session, tmp_path, monkeypatch) -> None:
    from app.repositories.uploaded_image_repository import UploadedImageRepository
    from app.models.user import User

    user = User(device_id=f"device-{uuid4()}")
    session.add(user)
    session.flush()
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-processing",
        original_image_key="users/user-1/images/image-1/original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    job = AvatarJob(
        user_id=user.id,
        image_id=image.id,
        status=AvatarJobStatus.PROCESSING,
        progress=5,
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        schema_version="1.0",
    )
    session.add(job)
    session.commit()

    monkeypatch.setattr(avatar_tasks, "SessionLocal", lambda: session)

    def fail_if_called(*_, **__):
        raise AssertionError("duplicate delivery should not run pipeline")

    monkeypatch.setattr(avatar_tasks, "generate_cartoon_avatar", fail_if_called)

    task = avatar_tasks.process_avatar_job._get_current_object()
    task.push_request(hostname="worker-1", id="task-1")
    try:
        task.run(str(job.id))
    finally:
        task.pop_request()


class FakeCeleryTask:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def apply_async(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("broker unavailable")
        return type("AsyncResult", (), {"id": kwargs.get("task_id")})()


def test_dispatch_outbox_sends_event_and_marks_sent(session, monkeypatch) -> None:
    fake_task = FakeCeleryTask()
    repo = OutboxEventRepository(session)
    event = repo.create_avatar_job_event(job_id=uuid4(), task_id="task-1", queue="avatar_gpu")
    event_id = event.id
    session.commit()

    DispatchSessionLocal = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(avatar_tasks, "SessionLocal", DispatchSessionLocal)
    monkeypatch.setattr(avatar_tasks, "process_avatar_job", fake_task)

    dispatched = avatar_tasks.dispatch_outbox.run()
    session.expire_all()
    event = session.get(type(event), event_id)

    assert dispatched == 1
    assert event.status == OutboxEventStatus.SENT
    assert fake_task.calls == [
        {
            "args": [event.payload["job_id"]],
            "queue": "avatar_gpu",
            "task_id": "task-1",
        }
    ]


def test_dispatch_outbox_failure_schedules_retry(session, monkeypatch) -> None:
    fake_task = FakeCeleryTask(fail=True)
    repo = OutboxEventRepository(session)
    event = repo.create_avatar_job_event(job_id=uuid4(), task_id="task-1", queue="avatar_gpu")
    event_id = event.id
    session.commit()

    DispatchSessionLocal = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(avatar_tasks, "SessionLocal", DispatchSessionLocal)
    monkeypatch.setattr(avatar_tasks, "process_avatar_job", fake_task)

    dispatched = avatar_tasks.dispatch_outbox.run()
    session.expire_all()
    event = session.get(type(event), event_id)

    assert dispatched == 0
    assert event.status == OutboxEventStatus.PENDING
    assert event.retry_count == 1
    assert event.next_retry_at is not None
    assert "broker unavailable" in event.last_error


def test_redispatch_stale_queued_jobs_creates_missing_outbox(session, monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    from app.repositories.uploaded_image_repository import UploadedImageRepository
    from app.models.user import User

    user = User(device_id=f"device-{uuid4()}")
    session.add(user)
    session.flush()
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-stale-queued",
        original_image_key="original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    job = AvatarJob(
        user_id=user.id,
        image_id=image.id,
        status=AvatarJobStatus.QUEUED,
        progress=0,
        celery_task_id="task-stale",
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        schema_version="1.0",
    )
    session.add(job)
    session.flush()
    job.created_at = datetime.now(timezone.utc) - timedelta(seconds=1200)
    session.commit()

    DispatchSessionLocal = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(avatar_tasks, "SessionLocal", DispatchSessionLocal)

    created = avatar_tasks.redispatch_stale_queued_jobs.run()

    assert created == 1
    outbox = session.query(OutboxEvent).one()
    assert outbox.status == OutboxEventStatus.PENDING
    assert outbox.payload["job_id"] == str(job.id)
    assert outbox.payload["task_id"] == "task-stale"


def test_redispatch_stale_queued_jobs_skips_existing_open_outbox(session, monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    from app.repositories.uploaded_image_repository import UploadedImageRepository
    from app.models.user import User

    user = User(device_id=f"device-{uuid4()}")
    session.add(user)
    session.flush()
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-stale-open-outbox",
        original_image_key="original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    job = AvatarJob(
        user_id=user.id,
        image_id=image.id,
        status=AvatarJobStatus.QUEUED,
        progress=0,
        celery_task_id="task-open",
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        schema_version="1.0",
    )
    session.add(job)
    session.flush()
    job.created_at = datetime.now(timezone.utc) - timedelta(seconds=1200)
    OutboxEventRepository(session).create_avatar_job_event(
        job_id=job.id,
        task_id="task-open",
        queue="avatar_gpu",
    )
    session.commit()

    DispatchSessionLocal = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(avatar_tasks, "SessionLocal", DispatchSessionLocal)

    created = avatar_tasks.redispatch_stale_queued_jobs.run()

    assert created == 0
    assert session.query(OutboxEvent).count() == 1
