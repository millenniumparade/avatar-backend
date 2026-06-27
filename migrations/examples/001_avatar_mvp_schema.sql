-- Example PostgreSQL schema for the avatar generation MVP.
-- This file is a design sample, not an Alembic migration.
-- Use it as the source for the first real Alembic revision.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(128) UNIQUE,
    username VARCHAR(128),
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE uploaded_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    image_hash VARCHAR(128) NOT NULL,
    original_image_key VARCHAR(512) NOT NULL,
    thumbnail_key VARCHAR(512),
    mime_type VARCHAR(64) NOT NULL,
    file_size INTEGER NOT NULL,
    width INTEGER,
    height INTEGER,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT ck_uploaded_images_status
        CHECK (status IN ('active', 'deleted'))
);

CREATE UNIQUE INDEX uq_uploaded_images_active_hash
    ON uploaded_images(user_id, image_hash)
    WHERE status = 'active';

CREATE INDEX ix_uploaded_images_user_created
    ON uploaded_images(user_id, created_at DESC);

CREATE INDEX ix_uploaded_images_hash
    ON uploaded_images(image_hash);

CREATE TABLE avatar_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    image_id UUID NOT NULL REFERENCES uploaded_images(id),
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    current_stage VARCHAR(64),
    result_id UUID,
    celery_task_id VARCHAR(128),
    worker_id VARCHAR(128),
    cache_hit BOOLEAN NOT NULL DEFAULT false,
    retry_count INTEGER NOT NULL DEFAULT 0,
    algorithm_version VARCHAR(64) NOT NULL,
    asset_library_version VARCHAR(64) NOT NULL,
    schema_version VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CONSTRAINT ck_avatar_jobs_status
        CHECK (status IN ('queued', 'processing', 'retrying', 'succeeded', 'failed', 'timeout', 'cancelled')),
    CONSTRAINT ck_avatar_jobs_progress
        CHECK (progress >= 0 AND progress <= 100),
    CONSTRAINT ck_avatar_jobs_retry_count
        CHECK (retry_count >= 0)
);

CREATE INDEX ix_avatar_jobs_user_created
    ON avatar_jobs(user_id, created_at DESC);

CREATE UNIQUE INDEX uq_avatar_jobs_one_active_per_user
    ON avatar_jobs(user_id)
    WHERE status IN ('queued', 'processing', 'retrying');

CREATE INDEX ix_avatar_jobs_user_image
    ON avatar_jobs(user_id, image_id);

CREATE INDEX ix_avatar_jobs_status
    ON avatar_jobs(status);

CREATE INDEX ix_avatar_jobs_celery_task
    ON avatar_jobs(celery_task_id);

CREATE INDEX ix_avatar_jobs_heartbeat
    ON avatar_jobs(heartbeat_at);

CREATE INDEX ix_avatar_jobs_worker
    ON avatar_jobs(worker_id);

CREATE TABLE avatar_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    image_id UUID NOT NULL REFERENCES uploaded_images(id),
    job_id UUID NOT NULL REFERENCES avatar_jobs(id),
    result_json JSONB NOT NULL,
    result_json_key VARCHAR(512),
    preview_image_key VARCHAR(512),
    schema_version VARCHAR(32) NOT NULL,
    algorithm_version VARCHAR(64) NOT NULL,
    asset_library_version VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT ck_avatar_results_status
        CHECK (status IN ('active', 'deleted'))
);

ALTER TABLE avatar_jobs
    ADD CONSTRAINT fk_avatar_jobs_result
    FOREIGN KEY (result_id) REFERENCES avatar_results(id);

CREATE UNIQUE INDEX uq_avatar_results_active_version
    ON avatar_results(
        user_id,
        image_id,
        algorithm_version,
        asset_library_version,
        schema_version
    )
    WHERE status = 'active';

CREATE INDEX ix_avatar_results_user_created
    ON avatar_results(user_id, created_at DESC);

CREATE INDEX ix_avatar_results_image
    ON avatar_results(image_id);

CREATE INDEX ix_avatar_results_result_json_gin
    ON avatar_results USING GIN (result_json);

CREATE TABLE avatar_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES avatar_jobs(id),
    artifact_type VARCHAR(64) NOT NULL,
    object_key VARCHAR(512) NOT NULL,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX ix_avatar_artifacts_job
    ON avatar_artifacts(job_id);

CREATE INDEX ix_avatar_artifacts_type
    ON avatar_artifacts(artifact_type);

CREATE INDEX ix_avatar_artifacts_expires
    ON avatar_artifacts(expires_at)
    WHERE expires_at IS NOT NULL;
