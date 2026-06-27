"""Redis client factory for business admission controls."""

from __future__ import annotations

from functools import lru_cache

from redis import Redis

from app.core.config import settings


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    """Return a shared Redis client."""

    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=settings.redis_health_check_interval_seconds,
    )
