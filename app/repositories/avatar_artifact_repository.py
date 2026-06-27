"""Repository for avatar_artifacts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.avatar_artifact import AvatarArtifact


class AvatarArtifactRepository:
    """Database operations for intermediate generation artifacts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, artifact: AvatarArtifact) -> AvatarArtifact:
        """Persist one artifact row."""

        self.session.add(artifact)
        self.session.flush()
        return artifact

    def list_by_job(self, job_id: UUID | str) -> list[AvatarArtifact]:
        """List artifacts for a job in creation order."""

        stmt = (
            select(AvatarArtifact)
            .where(AvatarArtifact.job_id == job_id)
            .order_by(AvatarArtifact.created_at.asc(), AvatarArtifact.id.asc())
        )
        return list(self.session.scalars(stmt))
