"""create avatar mvp schema

Revision ID: 20260516_0001
Revises:
Create Date: 2026-05-16 01:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260516_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "avatar_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("asset_index", sa.Integer(), nullable=False),
        sa.Column("asset_name", sa.String(length=128), nullable=False),
        sa.Column("asset_version", sa.String(length=64), nullable=False),
        sa.Column("feature_vector_key", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_avatar_assets_type"), "avatar_assets", ["type"], unique=False)

    op.create_table(
        "uploaded_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("image_hash", sa.String(length=128), nullable=False),
        sa.Column("original_image_key", sa.String(length=512), nullable=False),
        sa.Column("thumbnail_key", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'deleted')", name="ck_uploaded_images_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_uploaded_images_image_hash"), "uploaded_images", ["image_hash"], unique=False)
    op.create_index(op.f("ix_uploaded_images_status"), "uploaded_images", ["status"], unique=False)
    op.create_index(op.f("ix_uploaded_images_user_id"), "uploaded_images", ["user_id"], unique=False)
    op.create_index(
        "uq_uploaded_images_active_hash",
        "uploaded_images",
        ["user_id", "image_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "avatar_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("image_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_id", sa.Uuid(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("asset_library_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_avatar_jobs_progress"),
        sa.CheckConstraint("retry_count >= 0", name="ck_avatar_jobs_retry_count"),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'retrying', 'succeeded', 'failed', 'timeout', 'cancelled')",
            name="ck_avatar_jobs_status",
        ),
        sa.ForeignKeyConstraint(["image_id"], ["uploaded_images.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_avatar_jobs_celery_task_id"), "avatar_jobs", ["celery_task_id"], unique=False)
    op.create_index(op.f("ix_avatar_jobs_heartbeat_at"), "avatar_jobs", ["heartbeat_at"], unique=False)
    op.create_index(op.f("ix_avatar_jobs_image_id"), "avatar_jobs", ["image_id"], unique=False)
    op.create_index(op.f("ix_avatar_jobs_status"), "avatar_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_avatar_jobs_user_id"), "avatar_jobs", ["user_id"], unique=False)
    op.create_index(op.f("ix_avatar_jobs_worker_id"), "avatar_jobs", ["worker_id"], unique=False)
    op.create_index(
        "uq_avatar_jobs_one_active_per_user",
        "avatar_jobs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'processing', 'retrying')"),
    )

    op.create_table(
        "avatar_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("image_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_json_key", sa.String(length=512), nullable=True),
        sa.Column("preview_image_key", sa.String(length=512), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("asset_library_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'deleted')", name="ck_avatar_results_status"),
        sa.ForeignKeyConstraint(["image_id"], ["uploaded_images.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["avatar_jobs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_avatar_results_image_id"), "avatar_results", ["image_id"], unique=False)
    op.create_index(op.f("ix_avatar_results_job_id"), "avatar_results", ["job_id"], unique=False)
    op.create_index(op.f("ix_avatar_results_status"), "avatar_results", ["status"], unique=False)
    op.create_index(op.f("ix_avatar_results_user_id"), "avatar_results", ["user_id"], unique=False)
    op.create_index(
        "uq_avatar_results_active_version",
        "avatar_results",
        ["user_id", "image_id", "algorithm_version", "asset_library_version", "schema_version"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_avatar_results_result_json_gin",
        "avatar_results",
        ["result_json"],
        unique=False,
        postgresql_using="gin",
    )

    op.create_foreign_key(
        "fk_avatar_jobs_result",
        "avatar_jobs",
        "avatar_results",
        ["result_id"],
        ["id"],
    )

    op.create_table(
        "avatar_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["avatar_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_avatar_artifacts_artifact_type"), "avatar_artifacts", ["artifact_type"], unique=False)
    op.create_index(op.f("ix_avatar_artifacts_expires_at"), "avatar_artifacts", ["expires_at"], unique=False)
    op.create_index(op.f("ix_avatar_artifacts_job_id"), "avatar_artifacts", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_avatar_artifacts_job_id"), table_name="avatar_artifacts")
    op.drop_index(op.f("ix_avatar_artifacts_expires_at"), table_name="avatar_artifacts")
    op.drop_index(op.f("ix_avatar_artifacts_artifact_type"), table_name="avatar_artifacts")
    op.drop_table("avatar_artifacts")

    op.drop_constraint("fk_avatar_jobs_result", "avatar_jobs", type_="foreignkey")

    op.drop_index("ix_avatar_results_result_json_gin", table_name="avatar_results", postgresql_using="gin")
    op.drop_index("uq_avatar_results_active_version", table_name="avatar_results", postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f("ix_avatar_results_user_id"), table_name="avatar_results")
    op.drop_index(op.f("ix_avatar_results_status"), table_name="avatar_results")
    op.drop_index(op.f("ix_avatar_results_job_id"), table_name="avatar_results")
    op.drop_index(op.f("ix_avatar_results_image_id"), table_name="avatar_results")
    op.drop_table("avatar_results")

    op.drop_index(op.f("ix_avatar_jobs_user_id"), table_name="avatar_jobs")
    op.drop_index(op.f("ix_avatar_jobs_worker_id"), table_name="avatar_jobs")
    op.drop_index("uq_avatar_jobs_one_active_per_user", table_name="avatar_jobs")
    op.drop_index(op.f("ix_avatar_jobs_status"), table_name="avatar_jobs")
    op.drop_index(op.f("ix_avatar_jobs_image_id"), table_name="avatar_jobs")
    op.drop_index(op.f("ix_avatar_jobs_heartbeat_at"), table_name="avatar_jobs")
    op.drop_index(op.f("ix_avatar_jobs_celery_task_id"), table_name="avatar_jobs")
    op.drop_table("avatar_jobs")

    op.drop_index("uq_uploaded_images_active_hash", table_name="uploaded_images", postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f("ix_uploaded_images_user_id"), table_name="uploaded_images")
    op.drop_index(op.f("ix_uploaded_images_status"), table_name="uploaded_images")
    op.drop_index(op.f("ix_uploaded_images_image_hash"), table_name="uploaded_images")
    op.drop_table("uploaded_images")

    op.drop_index(op.f("ix_avatar_assets_type"), table_name="avatar_assets")
    op.drop_table("avatar_assets")

    op.drop_table("users")
