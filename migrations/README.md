# Migrations

This directory stores Alembic database migration files.

The current MVP schema sample is:

- `migrations/examples/001_avatar_mvp_schema.sql`
- `docs/database_schema.md`

The SQL file is a design sample for the first real Alembic revision. Do not
apply it manually in production.

Recommended next steps:

1. Align SQLAlchemy ORM models with the MVP schema.
2. Initialize the full Alembic environment.
3. Generate the first migration for `users`, `uploaded_images`, `avatar_jobs`,
   `avatar_results`, and `avatar_artifacts`.
4. Add migration tests for upgrade and rollback.
