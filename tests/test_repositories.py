from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.avatar_job import AvatarJob, AvatarJobStatus
from app.models.avatar_result import AvatarResult, AvatarResultStatus
from app.models.user import User
from app.repositories.avatar_job_repository import AvatarJobRepository
from app.repositories.avatar_result_repository import AvatarResultRepository
from app.repositories.uploaded_image_repository import UploadedImageRepository


def create_user(session: Session) -> User:
    user = User(device_id="device-1")
    session.add(user)
    session.flush()
    return user


def test_uploaded_image_get_or_create_reuses_active_hash(session: Session) -> None:
    user = create_user(session)
    repo = UploadedImageRepository(session)

    image, created = repo.get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-1",
        original_image_key="users/u/images/i/original.jpg",
        mime_type="image/jpeg",
        file_size=128,
        width=512,
        height=512,
    )
    same_image, same_created = repo.get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-1",
        original_image_key="ignored.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )

    assert created is True
    assert same_created is False
    assert same_image.id == image.id
    assert repo.list_by_user(user.id) == [image]


def test_result_cache_lookup_and_soft_delete(session: Session) -> None:
    user = create_user(session)
    image_repo = UploadedImageRepository(session)
    job_repo = AvatarJobRepository(session)
    result_repo = AvatarResultRepository(session)
    image, _ = image_repo.get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-1",
        original_image_key="original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    job = job_repo.create(
        AvatarJob(
            user_id=user.id,
            image_id=image.id,
            status=AvatarJobStatus.PROCESSING,
            progress=50,
            algorithm_version="algo-1",
            asset_library_version="assets-1",
            schema_version="1.0",
        )
    )
    result = result_repo.create(
        AvatarResult(
            user_id=user.id,
            image_id=image.id,
            job_id=job.id,
            result_json={"schema_version": "1.0"},
            algorithm_version="algo-1",
            asset_library_version="assets-1",
            schema_version="1.0",
        )
    )
    job_repo.mark_succeeded(job.id, result.id)

    cached = result_repo.find_active_by_image_version(
        user_id=user.id,
        image_id=image.id,
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        schema_version="1.0",
    )
    assert cached is not None
    assert cached.id == result.id

    result_repo.soft_delete(result.id)
    assert result.status == AvatarResultStatus.DELETED
    assert (
        result_repo.find_active_by_image_version(
            user_id=user.id,
            image_id=image.id,
            algorithm_version="algo-1",
            asset_library_version="assets-1",
            schema_version="1.0",
        )
        is None
    )


def test_job_status_transitions_and_cancel_by_image(session: Session) -> None:
    user = create_user(session)
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-1",
        original_image_key="original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    repo = AvatarJobRepository(session)
    queued = repo.create(
        AvatarJob(
            user_id=user.id,
            image_id=image.id,
            status=AvatarJobStatus.QUEUED,
            progress=0,
            algorithm_version="algo-1",
            asset_library_version="assets-1",
            schema_version="1.0",
        )
    )
    processing = repo.update_status(
        queued.id,
        AvatarJobStatus.PROCESSING,
        40,
        stage="face_detecting",
        celery_task_id="task-1",
    )

    assert processing is not None
    assert processing.status == AvatarJobStatus.PROCESSING
    assert processing.progress == 40
    assert processing.current_stage == "face_detecting"
    assert processing.started_at is not None
    assert processing.heartbeat_at is not None

    cancelled_count = repo.cancel_by_image(user.id, image.id)
    assert cancelled_count == 1
    assert queued.status == AvatarJobStatus.CANCELLED
    assert queued.finished_at is not None


def test_stale_processing_jobs_expire_to_timeout(session: Session) -> None:
    user = create_user(session)
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash="hash-1",
        original_image_key="original.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    repo = AvatarJobRepository(session)
    stale = repo.create(
        AvatarJob(
            user_id=user.id,
            image_id=image.id,
            status=AvatarJobStatus.PROCESSING,
            progress=60,
            heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=300),
            algorithm_version="algo-1",
            asset_library_version="assets-1",
            schema_version="1.0",
        )
    )

    expired = repo.expire_stale_processing(heartbeat_timeout_seconds=120)

    assert len(expired) == 1
    assert stale.status == AvatarJobStatus.TIMEOUT
    assert stale.error_code == "PROCESSING_TIMEOUT"
    assert stale.finished_at is not None
