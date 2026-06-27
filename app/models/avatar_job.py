"""Avatar generation job ORM model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AvatarJobStatus(StrEnum):
    """Job lifecycle state."""

    QUEUED = "queued"
    PROCESSING = "processing"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AvatarJobStage(StrEnum):
    """Algorithm processing stage."""

    IMAGE_PREPARING = "image_preparing"
    FACE_DETECTING = "face_detecting"
    FACE_ALIGNING = "face_aligning"
    FACE_PARSING = "face_parsing"
    FACEVERSE_RECONSTRUCTION = "faceverse_reconstruction"
    MESH_EXTRACTING = "mesh_extracting"
    CARTOON_FITTING = "cartoon_fitting"
    PART_MATCHING = "part_matching"
    RESULT_BUILDING = "result_building"


class AvatarJob(Base):
    """One avatar generation request."""

    __tablename__ = "avatar_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'retrying', 'succeeded', 'failed', 'timeout', 'cancelled')",
            name="ck_avatar_jobs_status",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_avatar_jobs_progress"),
        CheckConstraint("retry_count >= 0", name="ck_avatar_jobs_retry_count"),
        Index(
            "uq_avatar_jobs_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'processing', 'retrying')"),
            sqlite_where=text("status IN ('queued', 'processing', 'retrying')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    image_id: Mapped[UUID] = mapped_column(ForeignKey("uploaded_images.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=AvatarJobStatus.QUEUED, index=True)
    result_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("avatar_results.id", use_alter=True, name="fk_avatar_jobs_result"),
        nullable=True,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    algorithm_version: Mapped[str] = mapped_column(String(64))
    asset_library_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="jobs")
    image: Mapped[UploadedImage] = relationship(back_populates="jobs")
    result: Mapped[AvatarResult | None] = relationship(
        back_populates="jobs",
        foreign_keys=[result_id],
    )
    produced_result: Mapped[AvatarResult | None] = relationship(
        back_populates="source_job",
        foreign_keys="AvatarResult.job_id",
    )
    artifacts: Mapped[list[AvatarArtifact]] = relationship(back_populates="job")
