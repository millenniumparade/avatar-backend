from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.core.errors import AvatarError, ErrorCode
from app.services.rate_limit_service import RateLimitService
from tests.fakes import FailingRedis, FakeRedis


def run_async(coro):
    return asyncio.run(coro)


def test_active_job_lock_uses_set_nx_semantics() -> None:
    service = RateLimitService(FakeRedis())
    first = run_async(service.acquire_job_admission("user-1"))
    service.bind_active_job(first, "job-1")

    with pytest.raises(AvatarError) as exc_info:
        run_async(service.acquire_job_admission("user-1"))

    assert exc_info.value.code == ErrorCode.ACTIVE_JOB_EXISTS
    assert "job-1" in exc_info.value.message

    run_async(service.release_active_job("user-1"))
    second = run_async(service.acquire_job_admission("user-1"))
    assert second.active_lock_acquired is True


def test_global_capacity_rejects_before_active_lock(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_global_active_jobs", 1)
    redis = FakeRedis()
    service = RateLimitService(redis)

    run_async(service.acquire_job_admission("user-1"))
    with pytest.raises(AvatarError) as exc_info:
        run_async(service.acquire_job_admission("user-2"))

    assert exc_info.value.code == ErrorCode.QUEUE_FULL
    assert redis.get("avatar:global_active_jobs") == "1"
    assert redis.get("avatar:active_job:user-2") is None


def test_admission_redis_timeout_returns_queue_unavailable() -> None:
    service = RateLimitService(FailingRedis(fail_on={"incr"}))

    with pytest.raises(AvatarError) as exc_info:
        run_async(service.acquire_job_admission("user-1"))

    assert exc_info.value.code == ErrorCode.QUEUE_UNAVAILABLE
    assert exc_info.value.status_code == 503


def test_release_active_job_best_effort_swallows_redis_timeout() -> None:
    service = RateLimitService(FailingRedis(fail_on={"delete", "decr"}))

    assert service.release_active_job_best_effort("user-1") is False


def test_release_active_job_with_job_id_does_not_delete_newer_lock() -> None:
    redis = FakeRedis()
    service = RateLimitService(redis)
    first = run_async(service.acquire_job_admission("user-1"))
    service.bind_active_job(first, "job-1")
    run_async(service.release_active_job("user-1", "job-1"))

    second = run_async(service.acquire_job_admission("user-1"))
    service.bind_active_job(second, "job-2")

    assert service.release_active_job_best_effort("user-1", job_id="job-1") is False
    assert redis.get("avatar:active_job:user-1") == "job-2"
