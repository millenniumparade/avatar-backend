"""Repository for avatar_jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.avatar_job import AvatarJob, AvatarJobStatus


class AvatarJobRepository:
    """Database operations for avatar generation jobs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, job: AvatarJob) -> AvatarJob:
        """Persist a job row."""

        self.session.add(job)
        self.session.flush()
        return job

    def get_by_id(self, job_id: UUID | str) -> AvatarJob | None:
        """Return one job by ID."""

        return self.session.get(AvatarJob, _as_uuid(job_id))

    def list_by_user(self, user_id: UUID | str, limit: int = 20, offset: int = 0) -> list[AvatarJob]:
        """List jobs for a user, newest first."""

        stmt = (
            select(AvatarJob)
            .where(AvatarJob.user_id == _as_uuid(user_id))
            .order_by(AvatarJob.created_at.desc(), AvatarJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt))

    def count_active_by_user(self, user_id: UUID | str) -> int:
        """Count queued, retrying, and processing jobs for one user."""

        stmt = select(AvatarJob).where(
            AvatarJob.user_id == _as_uuid(user_id),
            AvatarJob.status.in_(
                [AvatarJobStatus.QUEUED, AvatarJobStatus.PROCESSING, AvatarJobStatus.RETRYING]
            ),
        )
        return len(list(self.session.scalars(stmt)))

    def find_active_by_user(self, user_id: UUID | str) -> AvatarJob | None:
        """Return one queued, retrying, or processing job for a user."""

        stmt = (
            select(AvatarJob)
            .where(
                AvatarJob.user_id == _as_uuid(user_id),
                AvatarJob.status.in_(
                    [AvatarJobStatus.QUEUED, AvatarJobStatus.PROCESSING, AvatarJobStatus.RETRYING]
                ),
            )
            .order_by(AvatarJob.created_at.desc(), AvatarJob.id.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def update_status(
        self,
        job_id: UUID | str,
        status: str,
        progress: int,
        stage: str | None = None,
        celery_task_id: str | None = None,
        worker_id: str | None = None,
    ) -> AvatarJob | None:
        """Update job status, progress, and current stage."""

        job = self.get_by_id(job_id)
        if job is None:
            return None

        now = datetime.now(timezone.utc)
        previous_status = job.status
        job.status = status
        job.progress = progress
        job.current_stage = stage
        if celery_task_id is not None:
            job.celery_task_id = celery_task_id
        if worker_id is not None:
            job.worker_id = worker_id
        if status == AvatarJobStatus.PROCESSING and previous_status != AvatarJobStatus.PROCESSING:
            job.started_at = now
        if status in {AvatarJobStatus.PROCESSING, AvatarJobStatus.RETRYING}:
            job.heartbeat_at = now
        if status in {
            AvatarJobStatus.SUCCEEDED,
            AvatarJobStatus.FAILED,
            AvatarJobStatus.TIMEOUT,
            AvatarJobStatus.CANCELLED,
        }:
            job.finished_at = now

        self.session.flush()
        return job

    def set_celery_task_id(self, job_id: UUID | str, celery_task_id: str) -> AvatarJob | None:
        """Persist the deterministic Celery task ID before dispatch."""

        job = self.get_by_id(job_id)
        if job is None:
            return None

        job.celery_task_id = celery_task_id
        self.session.flush()
        return job

    def claim_for_processing(
        self,
        job_id: UUID | str,
        *,
        celery_task_id: str,
        worker_id: str,
    ) -> bool:
        """Atomically claim a queued/retrying job for one worker.

        Duplicate Celery deliveries should not run the pipeline twice. This
        update succeeds only for jobs that are still dispatchable.
        """

        now = datetime.now(timezone.utc)
        stmt = (
            update(AvatarJob)
            .where(
                AvatarJob.id == _as_uuid(job_id),
                AvatarJob.status.in_([AvatarJobStatus.QUEUED, AvatarJobStatus.RETRYING]),
            )
            .values(
                status=AvatarJobStatus.PROCESSING,
                progress=5,
                current_stage="image_preparing",
                celery_task_id=celery_task_id,
                worker_id=worker_id,
                started_at=now,
                heartbeat_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount == 1

    def touch_heartbeat(
        self,
        job_id: UUID | str,
        *,
        progress: int | None = None,
        stage: str | None = None,
        worker_id: str | None = None,
    ) -> AvatarJob | None:
        """Refresh processing heartbeat and optional progress fields."""

        job = self.get_by_id(job_id)
        if job is None:
            return None

        job.heartbeat_at = datetime.now(timezone.utc)
        if progress is not None:
            job.progress = progress
        if stage is not None:
            job.current_stage = stage
        if worker_id is not None:
            job.worker_id = worker_id
        self.session.flush()
        return job

    def mark_retrying(self, job_id: UUID | str, error_code: str, error_message: str) -> AvatarJob | None:
        """Mark a failed attempt as retrying before Celery schedules another try."""

        job = self.get_by_id(job_id)
        if job is None:
            return None

        job.status = AvatarJobStatus.RETRYING
        job.retry_count += 1
        job.error_code = error_code
        job.error_message = error_message
        job.heartbeat_at = datetime.now(timezone.utc)
        self.session.flush()
        return job

    def mark_succeeded(
        self,
        job_id: UUID | str,
        result_id: UUID | str,
        *,
        cache_hit: bool = False,
    ) -> AvatarJob | None:
        """Mark a job as succeeded and attach its result."""

        job = self.get_by_id(job_id)
        if job is None:
            return None

        job.status = AvatarJobStatus.SUCCEEDED
        job.progress = 100
        job.result_id = _as_uuid(result_id)
        job.cache_hit = cache_hit
        job.error_code = None
        job.error_message = None
        job.heartbeat_at = datetime.now(timezone.utc)
        job.finished_at = datetime.now(timezone.utc)
        self.session.flush()
        return job

    def mark_failed(
        self,
        job_id: UUID | str,
        error_code: str,
        error_message: str,
        *,
        status: str = AvatarJobStatus.FAILED,
    ) -> AvatarJob | None:
        """Mark a job as failed with a structured error."""

        job = self.get_by_id(job_id)
        if job is None:
            return None

        job.status = status
        job.progress = min(job.progress, 99)
        job.error_code = error_code
        job.error_message = error_message
        job.heartbeat_at = datetime.now(timezone.utc)
        job.finished_at = datetime.now(timezone.utc)
        self.session.flush()
        return job

    def find_stale_processing(self, *, heartbeat_timeout_seconds: int, limit: int = 100) -> list[AvatarJob]:
        """Find processing jobs whose worker heartbeat is too old."""

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=heartbeat_timeout_seconds)
        stmt = (
            select(AvatarJob)
            .where(
                AvatarJob.status == AvatarJobStatus.PROCESSING,
                (AvatarJob.heartbeat_at.is_(None) | (AvatarJob.heartbeat_at < cutoff)),
            )
            .order_by(AvatarJob.started_at.asc().nullsfirst(), AvatarJob.created_at.asc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def find_stale_queued(self, *, queued_after_seconds: int, limit: int = 100) -> list[AvatarJob]:
        """Find queued jobs whose broker dispatch may have stalled."""

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=queued_after_seconds)
        stmt = (
            select(AvatarJob)
            .where(
                AvatarJob.status == AvatarJobStatus.QUEUED,
                AvatarJob.created_at < cutoff,
            )
            .order_by(AvatarJob.created_at.asc(), AvatarJob.id.asc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def expire_stale_processing(
        self,
        *,
        heartbeat_timeout_seconds: int,
        error_message: str = "Worker heartbeat timed out.",
        limit: int = 100,
    ) -> list[AvatarJob]:
        """Mark stale processing jobs as timeout so users do not see endless processing."""

        jobs = self.find_stale_processing(heartbeat_timeout_seconds=heartbeat_timeout_seconds, limit=limit)
        now = datetime.now(timezone.utc)
        for job in jobs:
            job.status = AvatarJobStatus.TIMEOUT
            job.error_code = "PROCESSING_TIMEOUT"
            job.error_message = error_message
            job.finished_at = now
        self.session.flush()
        return jobs

    def cancel_by_image(self, user_id: UUID | str, image_id: UUID | str) -> int:
        """Cancel unfinished jobs for a user's image."""

        stmt = select(AvatarJob).where(
            AvatarJob.user_id == _as_uuid(user_id),
            AvatarJob.image_id == _as_uuid(image_id),
            AvatarJob.status.in_([AvatarJobStatus.QUEUED, AvatarJobStatus.PROCESSING, AvatarJobStatus.RETRYING]),
        )
        jobs = list(self.session.scalars(stmt))
        now = datetime.now(timezone.utc)
        for job in jobs:
            job.status = AvatarJobStatus.CANCELLED
            job.finished_at = now
        self.session.flush()
        return len(jobs)


def _as_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))
