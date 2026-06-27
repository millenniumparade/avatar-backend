"""Redis-backed queue admission service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.errors import AvatarError, ErrorCode
from app.core.redis_client import get_redis_client


class RedisLike(Protocol):
    def set(self, name: str, value: str, nx: bool = False, ex: int | None = None):
        ...

    def get(self, name: str):
        ...

    def eval(self, script: str, numkeys: int, *keys_and_args):
        ...

    def delete(self, *names: str):
        ...

    def incr(self, name: str):
        ...

    def decr(self, name: str):
        ...

    def expire(self, name: str, time: int):
        ...


@dataclass(slots=True)
class ActiveJobAdmission:
    """Redis keys acquired before a job is written to storage or database."""

    user_id: str
    active_lock_key: str
    capacity_key: str
    active_lock_acquired: bool = False
    capacity_acquired: bool = False


class RateLimitService:
    """Protect API, storage, and database before accepting upload work."""

    def __init__(self, redis_client: RedisLike | None = None) -> None:
        self.redis = redis_client or get_redis_client()

    async def check_upload_rate(self, user_id: str, ip_address: str | None = None) -> None:
        """Placeholder for per-IP token bucket limiting."""

        return None

    async def acquire_job_admission(self, user_id: str) -> ActiveJobAdmission:
        """Acquire global capacity and single-active-job lock."""

        admission = ActiveJobAdmission(
            user_id=user_id,
            active_lock_key=self.active_job_lock_key(user_id),
            capacity_key=self.global_active_jobs_key(),
        )
        try:
            await self._acquire_global_capacity(admission)
            await self._acquire_active_job_lock(admission)
        except AvatarError:
            raise
        except RedisError as exc:
            self.release_job_admission_best_effort(admission)
            raise AvatarError(
                code=ErrorCode.QUEUE_UNAVAILABLE,
                message="Queue admission is temporarily unavailable. Please retry later.",
                status_code=503,
            ) from exc
        return admission

    async def release_job_admission(self, admission: ActiveJobAdmission) -> None:
        """Release any admission keys acquired before job creation."""

        self.release_job_admission_best_effort(admission)

    async def release_active_job(self, user_id: str, job_id: str | None = None) -> None:
        """Release a user's active-job lock when the job reaches a terminal state."""

        if job_id is None:
            self.redis.delete(self.active_job_lock_key(user_id))
            self.redis.decr(self.global_active_jobs_key())
        else:
            if self._delete_if_value_matches(self.active_job_lock_key(user_id), job_id):
                self.redis.decr(self.global_active_jobs_key())

    def release_job_admission_best_effort(self, admission: ActiveJobAdmission) -> bool:
        """Best-effort release for admission keys.

        Redis admission state is short-lived protection, not the source of job
        truth. A release failure must not turn a committed job into a failure.
        """

        released_active_lock = True
        released_capacity = True
        if admission.active_lock_acquired:
            released_active_lock = self._delete_best_effort(admission.active_lock_key)
            if released_active_lock:
                admission.active_lock_acquired = False
        if admission.capacity_acquired:
            released_capacity = self._decr_best_effort(admission.capacity_key)
            if released_capacity:
                admission.capacity_acquired = False
        return released_active_lock and released_capacity

    def release_active_job_best_effort(self, user_id: str, job_id: str | None = None) -> bool:
        """Best-effort release for a terminal job's Redis admission keys."""

        if job_id is None:
            deleted = self._delete_best_effort(self.active_job_lock_key(user_id))
            decremented = self._decr_best_effort(self.global_active_jobs_key())
        else:
            deleted = self._delete_if_value_matches_best_effort(self.active_job_lock_key(user_id), job_id)
            decremented = self._decr_best_effort(self.global_active_jobs_key()) if deleted else True
        return deleted and decremented

    async def _acquire_global_capacity(self, admission: ActiveJobAdmission) -> None:
        current = int(self.redis.incr(admission.capacity_key))
        self.redis.expire(admission.capacity_key, settings.active_job_lock_ttl_seconds)
        if current > settings.max_global_active_jobs:
            self.redis.decr(admission.capacity_key)
            raise AvatarError(
                code=ErrorCode.QUEUE_FULL,
                message=(
                    "System is busy. "
                    f"Please retry after {settings.global_queue_retry_after_seconds} seconds."
                ),
                status_code=429,
            )
        admission.capacity_acquired = True

    async def _acquire_active_job_lock(self, admission: ActiveJobAdmission) -> None:
        acquired = self.redis.set(
            admission.active_lock_key,
            "pending",
            nx=True,
            ex=settings.active_job_lock_ttl_seconds,
        )
        if not acquired:
            await self.release_job_admission(admission)
            existing_job_id = self.redis.get(admission.active_lock_key)
            message = "User already has an active avatar job."
            if existing_job_id and existing_job_id != "pending":
                message = f"User already has active avatar job {existing_job_id}."
            raise AvatarError(
                code=ErrorCode.ACTIVE_JOB_EXISTS,
                message=message,
                status_code=429,
            )
        admission.active_lock_acquired = True

    def bind_active_job(self, admission: ActiveJobAdmission, job_id: str) -> None:
        """Replace the pending lock value with the accepted job ID."""

        self.redis.set(admission.active_lock_key, job_id, ex=settings.active_job_lock_ttl_seconds)

    def bind_active_job_best_effort(self, admission: ActiveJobAdmission, job_id: str) -> bool:
        """Best-effort replacement of a pending active-job lock value."""

        try:
            self.bind_active_job(admission, job_id)
            return True
        except RedisError:
            return False

    def remember_active_job_best_effort(self, user_id: str, job_id: str) -> bool:
        """Best-effort cache repair when PostgreSQL still has an active job."""

        try:
            self.redis.set(
                self.active_job_lock_key(user_id),
                job_id,
                nx=True,
                ex=settings.active_job_lock_ttl_seconds,
            )
            return True
        except RedisError:
            return False

    def _delete_if_value_matches(self, key: str, expected_value: str) -> bool:
        script = (
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
            "return redis.call('DEL', KEYS[1]) "
            "else return 0 end"
        )
        return bool(self.redis.eval(script, 1, key, expected_value))

    def _delete_if_value_matches_best_effort(self, key: str, expected_value: str) -> bool:
        try:
            return self._delete_if_value_matches(key, expected_value)
        except (AttributeError, RedisError):
            try:
                if self.redis.get(key) == expected_value:
                    self.redis.delete(key)
                    return True
                return False
            except RedisError:
                return False

    def _delete_best_effort(self, key: str) -> bool:
        try:
            self.redis.delete(key)
            return True
        except RedisError:
            return False

    def _decr_best_effort(self, key: str) -> bool:
        try:
            self.redis.decr(key)
            return True
        except RedisError:
            return False

    @staticmethod
    def active_job_lock_key(user_id: str) -> str:
        return f"avatar:active_job:{user_id}"

    @staticmethod
    def global_active_jobs_key() -> str:
        return "avatar:global_active_jobs"


def get_rate_limit_service() -> RateLimitService:
    """Return the Redis-backed admission service."""

    return RateLimitService()
