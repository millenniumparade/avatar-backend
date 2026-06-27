"""Avatar generation result ORM model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AvatarResultStatus(StrEnum):
    """Lifecycle state for generated results."""

    ACTIVE = "active"
    DELETED = "deleted"


class AvatarResult(Base):
    """Reusable HumanInfo JSON generated for an image/version tuple."""

    __tablename__ = "avatar_results"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'deleted')", name="ck_avatar_results_status"),
        Index(
            "uq_avatar_results_active_version",
            "user_id",
            "image_id",
            "algorithm_version",
            "asset_library_version",
            "schema_version",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    image_id: Mapped[UUID] = mapped_column(ForeignKey("uploaded_images.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("avatar_jobs.id"), index=True)
    result_json: Mapped[dict] = mapped_column(JSON)
    result_json_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    preview_image_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(32))
    algorithm_version: Mapped[str] = mapped_column(String(64))
    asset_library_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default=AvatarResultStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="results")
    image: Mapped[UploadedImage] = relationship(back_populates="results")
    source_job: Mapped[AvatarJob] = relationship(
        back_populates="produced_result",
        foreign_keys=[job_id],
    )
    jobs: Mapped[list[AvatarJob]] = relationship(
        back_populates="result",
        foreign_keys="AvatarJob.result_id",
    )
