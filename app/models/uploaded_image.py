"""Uploaded image ORM model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ImageStatus(StrEnum):
    """Lifecycle state for user-uploaded images."""

    ACTIVE = "active"
    DELETED = "deleted"


class UploadedImage(Base):
    """Image uploaded by a user and reusable across generation jobs."""

    __tablename__ = "uploaded_images"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'deleted')", name="ck_uploaded_images_status"),
        Index(
            "uq_uploaded_images_active_hash",
            "user_id",
            "image_hash",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    image_hash: Mapped[str] = mapped_column(String(128), index=True)
    original_image_key: Mapped[str] = mapped_column(String(512))
    thumbnail_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=ImageStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="uploaded_images")
    jobs: Mapped[list[AvatarJob]] = relationship(back_populates="image")
    results: Mapped[list[AvatarResult]] = relationship(back_populates="image")
