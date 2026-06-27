from __future__ import annotations

import asyncio
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import UploadFile
from PIL import Image
from app.core.errors import AvatarError, ErrorCode
from app.models.avatar_job import AvatarJob, AvatarJobStatus
from app.models.outbox_event import OutboxEvent, OutboxEventStatus
from app.models.avatar_result import AvatarResult
from app.repositories.avatar_job_repository import AvatarJobRepository
from app.repositories.avatar_result_repository import AvatarResultRepository
from app.services.avatar_job_service import AvatarJobService
from app.services.rate_limit_service import RateLimitService
from app.services.storage_service import StorageService
from tests.fakes import FakeRedis


def make_png_bytes(size: tuple[int, int] = (16, 16)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color=(255, 0, 0)).save(output, format="PNG")
    return output.getvalue()


def make_upload(data: bytes, filename: str = "face.png") -> UploadFile:
    upload = UploadFile(filename=filename, file=BytesIO(data))
    upload.headers = {"content-type": "image/png"}
    return upload


def run_async(coro):
    return asyncio.run(coro)


class FakeTask:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def apply_async(self, **kwargs):
        self.calls.append(kwargs)
        return type("AsyncResult", (), {"id": kwargs.get("task_id")})()


@pytest.fixture()
def service(tmp_path, session):
    return AvatarJobService(
        session=session,
        storage_service=StorageService(storage_root=tmp_path),
        enqueue_tasks=False,
        rate_limit_service=RateLimitService(FakeRedis()),
    )


def test_create_avatar_job_persists_queued_job(service: AvatarJobService) -> None:
    response = run_async(service.create_job(make_upload(make_png_bytes())))

    assert response.status == AvatarJobStatus.QUEUED

    status = run_async(service.get_job_status(response.job_id))
    assert status.status == AvatarJobStatus.QUEUED
    assert status.progress == 0


def test_same_user_can_have_only_one_active_job(service: AvatarJobService) -> None:
    run_async(service.create_job(make_upload(make_png_bytes())))

    with pytest.raises(AvatarError) as exc_info:
        run_async(service.create_job(make_upload(make_png_bytes(size=(17, 16)))))

    assert exc_info.value.code == ErrorCode.ACTIVE_JOB_EXISTS


def test_redis_miss_falls_back_to_database_active_job(tmp_path, session) -> None:
    redis = FakeRedis()
    rate_limit_service = RateLimitService(redis)
    service = AvatarJobService(
        session=session,
        storage_service=StorageService(storage_root=tmp_path),
        enqueue_tasks=False,
        device_id="redis-miss-user",
        rate_limit_service=rate_limit_service,
    )

    first_response = run_async(service.create_job(make_upload(make_png_bytes())))
    job = session.get(AvatarJob, UUID(first_response.job_id))
    redis.delete("avatar:active_job:" + str(job.user_id))

    with pytest.raises(AvatarError) as exc_info:
        run_async(service.create_job(make_upload(make_png_bytes(size=(17, 16)))))

    assert exc_info.value.code == ErrorCode.ACTIVE_JOB_EXISTS
    assert redis.get("avatar:active_job:" + str(job.user_id)) == str(job.id)


def test_different_users_can_queue_independently(tmp_path, session) -> None:
    rate_limit_service = RateLimitService(FakeRedis())
    first = AvatarJobService(
        session=session,
        storage_service=StorageService(storage_root=tmp_path),
        enqueue_tasks=False,
        device_id="user-a",
        rate_limit_service=rate_limit_service,
    )
    second = AvatarJobService(
        session=session,
        storage_service=StorageService(storage_root=tmp_path),
        enqueue_tasks=False,
        device_id="user-b",
        rate_limit_service=rate_limit_service,
    )

    first_response = run_async(first.create_job(make_upload(make_png_bytes())))
    second_response = run_async(second.create_job(make_upload(make_png_bytes(size=(17, 16)))))

    assert first_response.status == AvatarJobStatus.QUEUED
    assert second_response.status == AvatarJobStatus.QUEUED


def test_create_avatar_job_rejects_invalid_extension(service: AvatarJobService) -> None:
    with pytest.raises(AvatarError) as exc_info:
        run_async(service.create_job(make_upload(b"bad", filename="face.gif")))

    assert exc_info.value.code == ErrorCode.INVALID_IMAGE_FORMAT


def test_cached_result_releases_active_lock(tmp_path, session) -> None:
    redis = FakeRedis()
    rate_limit_service = RateLimitService(redis)
    service = AvatarJobService(
        session=session,
        storage_service=StorageService(storage_root=tmp_path),
        enqueue_tasks=False,
        device_id="cache-user",
        rate_limit_service=rate_limit_service,
    )
    first_response = run_async(service.create_job(make_upload(make_png_bytes())))
    job = session.get(AvatarJob, UUID(first_response.job_id))
    result = AvatarResultRepository(session).create(
        AvatarResult(
            user_id=job.user_id,
            image_id=job.image_id,
            job_id=job.id,
            result_json={"hair": 22},
            algorithm_version="avatar-algo-0.1.0",
            asset_library_version="avatar-assets-2026-05",
            schema_version="1.0",
        )
    )
    AvatarJobRepository(session).mark_succeeded(job.id, result.id)
    run_async(rate_limit_service.release_active_job(str(job.user_id), str(job.id)))
    session.commit()

    cached_response = run_async(service.create_job(make_upload(make_png_bytes())))

    assert cached_response.status == AvatarJobStatus.SUCCEEDED
    assert redis.get("avatar:active_job:" + str(job.user_id)) is None


def test_create_job_writes_outbox_event_in_same_transaction(tmp_path, session, monkeypatch) -> None:
    fake_task = FakeTask()
    service = AvatarJobService(
        session=session,
        storage_service=StorageService(storage_root=tmp_path),
        enqueue_tasks=True,
        device_id="enqueue-user",
        rate_limit_service=RateLimitService(FakeRedis()),
    )

    response = run_async(service.create_job(make_upload(make_png_bytes())))
    job = session.get(AvatarJob, UUID(response.job_id))
    outbox = session.query(OutboxEvent).one()

    assert job.celery_task_id == f"avatar-job-{job.id}"
    assert outbox.status == OutboxEventStatus.PENDING
    assert outbox.event_type == "avatar.process_job"
    assert outbox.payload == {
        "job_id": str(job.id),
        "queue": "avatar_gpu",
        "task_id": f"avatar-job-{job.id}",
    }
    assert fake_task.calls == []
