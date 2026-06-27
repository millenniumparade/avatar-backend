"""User ORM model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """User or anonymous device owner."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    uploaded_images: Mapped[list[UploadedImage]] = relationship(back_populates="user")
    jobs: Mapped[list[AvatarJob]] = relationship(back_populates="user")
    results: Mapped[list[AvatarResult]] = relationship(back_populates="user")
