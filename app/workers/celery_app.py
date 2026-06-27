"""Celery application configuration."""

from celery import Celery
from kombu import Queue

from app.core.config import settings

celery_app = Celery(
    "avatar_backend",
    broker=settings.redis_url,
    backend=None,
    include=["app.workers.avatar_tasks"],
)

celery_app.conf.update(
    beat_schedule={
        "expire-stale-avatar-jobs": {
            "task": "avatar.expire_stale_jobs",
            "schedule": max(settings.job_heartbeat_timeout_seconds // 2, 30),
        },
        "dispatch-avatar-outbox": {
            "task": "avatar.dispatch_outbox",
            "schedule": settings.outbox_dispatch_interval_seconds,
        },
        "redispatch-stale-queued-avatar-jobs": {
            "task": "avatar.redispatch_stale_queued_jobs",
            "schedule": max(settings.queued_job_redispatch_after_seconds // 2, 60),
        },
    },
    task_acks_late=True,
    task_default_queue=settings.celery_task_default_queue,
    task_queues=(
        Queue(settings.celery_task_default_queue),
        Queue(settings.celery_gpu_queue),
    ),
    task_reject_on_worker_lost=True,
    task_routes={"avatar.process_job": {"queue": settings.celery_gpu_queue}},
    task_soft_time_limit=max(settings.job_timeout_seconds - settings.job_soft_timeout_margin_seconds, 1),
    task_time_limit=settings.job_timeout_seconds,
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    task_track_started=False,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "socket_connect_timeout": settings.redis_socket_connect_timeout_seconds,
        "socket_timeout": settings.redis_socket_timeout_seconds,
        "visibility_timeout": settings.celery_broker_visibility_timeout_seconds,
    },
    worker_concurrency=settings.worker_concurrency,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
)
