"""Outbox event ORM model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutboxEventStatus(StrEnum):
    """Outbox event lifecycle state."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class OutboxEvent(Base):
    """Message that must be dispatched after the business transaction commits."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed')",
            name="ck_outbox_events_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_outbox_events_retry_count"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default=OutboxEventStatus.PENDING, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=5)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
