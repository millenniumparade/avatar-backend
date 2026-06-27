"""Repository for outbox_events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.outbox_event import OutboxEvent, OutboxEventStatus


class OutboxEventRepository:
    """Database operations for reliable message dispatch."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_avatar_job_event(
        self,
        *,
        job_id: UUID | str,
        task_id: str,
        queue: str,
        max_retries: int = 5,
    ) -> OutboxEvent:
        """Create the outbox event that dispatches one avatar job."""

        event = OutboxEvent(
            event_type="avatar.process_job",
            payload={
                "job_id": str(job_id),
                "task_id": task_id,
                "queue": queue,
            },
            max_retries=max_retries,
            status=OutboxEventStatus.PENDING,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def has_open_avatar_job_event(self, job_id: UUID | str) -> bool:
        """Return whether a job already has a dispatchable outbox event."""

        stmt = select(OutboxEvent).where(
            OutboxEvent.event_type == "avatar.process_job",
            OutboxEvent.payload["job_id"].as_string() == str(job_id),
            OutboxEvent.status.in_(
                [OutboxEventStatus.PENDING, OutboxEventStatus.SENDING, OutboxEventStatus.SENT]
            ),
        )
        return self.session.scalars(stmt).first() is not None

    def claim_pending(
        self,
        *,
        dispatcher_id: str,
        limit: int = 50,
        stale_after_seconds: int = 300,
    ) -> list[OutboxEvent]:
        """Claim pending or stale sending events for this dispatcher."""

        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(seconds=stale_after_seconds)
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status.in_([OutboxEventStatus.PENDING, OutboxEventStatus.SENDING]),
                OutboxEvent.retry_count < OutboxEvent.max_retries,
                (OutboxEvent.next_retry_at.is_(None) | (OutboxEvent.next_retry_at <= now)),
                (
                    (OutboxEvent.status == OutboxEventStatus.PENDING)
                    | (OutboxEvent.locked_at.is_(None))
                    | (OutboxEvent.locked_at < stale_cutoff)
                ),
            )
            .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
            .limit(limit)
        )
        events = list(self.session.scalars(stmt))
        for event in events:
            event.status = OutboxEventStatus.SENDING
            event.locked_by = dispatcher_id
            event.locked_at = now
        self.session.flush()
        return events

    def mark_sent(self, event: OutboxEvent) -> None:
        """Mark one event as sent."""

        now = datetime.now(timezone.utc)
        event.status = OutboxEventStatus.SENT
        event.sent_at = now
        event.locked_by = None
        event.locked_at = None
        event.last_error = None
        self.session.flush()

    def mark_failed(
        self,
        event: OutboxEvent,
        error: str,
        *,
        retry_delay_seconds: int = 30,
    ) -> None:
        """Record dispatch failure and schedule retry if retries remain."""

        event.retry_count += 1
        event.last_error = error[:2000]
        event.locked_by = None
        event.locked_at = None
        if event.retry_count >= event.max_retries:
            event.status = OutboxEventStatus.FAILED
            event.next_retry_at = None
        else:
            event.status = OutboxEventStatus.PENDING
            event.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=retry_delay_seconds)
        self.session.flush()
