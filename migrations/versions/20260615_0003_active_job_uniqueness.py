"""add active avatar job uniqueness

Revision ID: 20260615_0003
Revises: 20260518_0002
Create Date: 2026-06-15 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260615_0003"
down_revision: Union[str, None] = "20260518_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_avatar_jobs_one_active_per_user",
        "avatar_jobs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'processing', 'retrying')"),
    )


def downgrade() -> None:
    op.drop_index("uq_avatar_jobs_one_active_per_user", table_name="avatar_jobs")
