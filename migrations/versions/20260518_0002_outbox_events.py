"""add outbox events

Revision ID: 20260518_0002
Revises: 20260516_0001
Create Date: 2026-05-18 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260518_0002"
down_revision: Union[str, None] = "20260516_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("retry_count >= 0", name="ck_outbox_events_retry_count"),
        sa.CheckConstraint("status IN ('pending', 'sending', 'sent', 'failed')", name="ck_outbox_events_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outbox_events_event_type"), "outbox_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_outbox_events_locked_by"), "outbox_events", ["locked_by"], unique=False)
    op.create_index(op.f("ix_outbox_events_next_retry_at"), "outbox_events", ["next_retry_at"], unique=False)
    op.create_index(op.f("ix_outbox_events_status"), "outbox_events", ["status"], unique=False)
    op.create_index(
        "ix_outbox_events_dispatch",
        "outbox_events",
        ["status", "next_retry_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_dispatch", table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_status"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_next_retry_at"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_locked_by"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_event_type"), table_name="outbox_events")
    op.drop_table("outbox_events")
