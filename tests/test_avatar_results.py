from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models.avatar_job import AvatarJob, AvatarJobStatus
from app.models.avatar_result import AvatarResult, AvatarResultStatus
from app.models.user import User
from app.repositories.uploaded_image_repository import UploadedImageRepository
from app.services.avatar_result_service import AvatarResultService


def run_async(coro):
    return asyncio.run(coro)


def create_result(
    session,
    *,
    image_hash: str = "hash-1",
    hair: int = 22,
    created_at: datetime | None = None,
) -> AvatarResult:
    user = User(device_id="anonymous-device")
    existing = session.query(User).filter(User.device_id == "anonymous-device").one_or_none()
    if existing is None:
        user = User(device_id="anonymous-device")
        session.add(user)
        session.flush()
    else:
        user = existing
    image, _ = UploadedImageRepository(session).get_or_create_by_hash(
        user_id=user.id,
        image_hash=image_hash,
        original_image_key=f"{image_hash}.jpg",
        mime_type="image/jpeg",
        file_size=128,
    )
    job = AvatarJob(
        user_id=user.id,
        image_id=image.id,
        status=AvatarJobStatus.SUCCEEDED,
        progress=100,
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        schema_version="1.0",
    )
    session.add(job)
    session.flush()
    result = AvatarResult(
        user_id=user.id,
        image_id=image.id,
        job_id=job.id,
        result_json={"hair": hair, "shapeKeys": []},
        schema_version="1.0",
        algorithm_version="algo-1",
        asset_library_version="assets-1",
        status=AvatarResultStatus.ACTIVE,
        created_at=created_at,
    )
    session.add(result)
    session.flush()
    return result


def test_get_and_list_avatar_result(session) -> None:
    result = create_result(session)
    service = AvatarResultService(session)

    response = run_async(service.get_result(str(result.id)))
    result_list = run_async(service.list_results())

    assert response.human_info["hair"] == 22
    assert response.algorithm_version == "algo-1"
    assert result_list.total == 1
    assert result_list.limit == 20
    assert result_list.offset == 0
    assert result_list.items[0].result_id == str(result.id)


def test_list_avatar_results_uses_limit_offset_and_total(session) -> None:
    base_time = datetime(2026, 5, 18, tzinfo=timezone.utc)
    create_result(session, image_hash="hash-1", hair=1, created_at=base_time)
    second = create_result(session, image_hash="hash-2", hair=2, created_at=base_time + timedelta(seconds=1))
    create_result(session, image_hash="hash-3", hair=3, created_at=base_time + timedelta(seconds=2))
    service = AvatarResultService(session)

    page = run_async(service.list_results(limit=1, offset=1))

    assert page.total == 3
    assert page.limit == 1
    assert page.offset == 1
    assert len(page.items) == 1
    assert page.items[0].result_id == str(second.id)


def test_delete_avatar_result_soft_deletes(session) -> None:
    result = create_result(session)
    service = AvatarResultService(session)

    run_async(service.delete_result(str(result.id)))

    assert result.status == AvatarResultStatus.DELETED
    with pytest.raises(Exception):
        run_async(service.get_result(str(result.id)))
