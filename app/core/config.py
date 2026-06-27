"""项目配置。

后续建议使用环境变量注入数据库、Redis、对象存储和算法版本配置。
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行时配置。

    输入:
        .env 文件或系统环境变量。

    输出:
        Settings 实例，供 API、Worker 和算法 pipeline 读取。
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_name: str = "Avatar Backend"
    api_version: str = "0.1.0"
    environment: str = "local"

    database_url: str = "postgresql+psycopg://avatar:avatar@postgres:5432/avatar"
    redis_url: str = "redis://redis:6379/0"
    redis_socket_connect_timeout_seconds: float = 5.0
    redis_socket_timeout_seconds: float = 5.0
    redis_health_check_interval_seconds: int = 30

    storage_root: str = "storage"
    max_image_size_mb: int = 5
    max_image_width: int = 2048
    max_image_height: int = 2048
    allowed_image_extensions: set[str] = Field(default_factory=lambda: {"jpg", "jpeg", "png", "webp"})
    default_user_device_id: str = "anonymous-device"
    max_active_jobs_per_user: int = 1
    active_job_lock_ttl_seconds: int = 600
    max_global_active_jobs: int = 100
    global_queue_retry_after_seconds: int = 15

    algorithm_mode: str = "mock"
    algorithm_version: str = "avatar-algo-0.1.0"
    asset_library_version: str = "avatar-assets-2026-05"
    result_schema_version: str = "1.0"
    job_timeout_seconds: int = 300
    mock_algorithm_delay_seconds: int = 10
    mock_human_info_path: str = "examples/HumanInfo(102).json"
    faceverse_v4_root: str = "FaceVerse_v4"
    faceverse_v4_device: str = "auto"
    faceverse_v4_allow_cpu_fallback: bool = False
    faceverse_v4_compute_vertices: bool = True
    job_soft_timeout_margin_seconds: int = 10
    job_heartbeat_timeout_seconds: int = 420
    celery_task_default_queue: str = "avatar_default"
    celery_gpu_queue: str = "avatar_gpu"
    celery_worker_prefetch_multiplier: int = 1
    celery_worker_max_tasks_per_child: int = 20
    celery_broker_visibility_timeout_seconds: int = 600
    worker_concurrency: int = 4
    outbox_dispatch_interval_seconds: int = 1
    outbox_dispatch_batch_size: int = 50
    outbox_retry_delay_seconds: int = 30
    outbox_lock_timeout_seconds: int = 300
    queued_job_redispatch_after_seconds: int = 600

    storage_backend: str = "local"
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket_name: str = "avatar"
    s3_region_name: str = "us-east-1"
    s3_secure: bool = False


settings = Settings()
