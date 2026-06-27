"""Repository for avatar_results."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.avatar_result import AvatarResult, AvatarResultStatus


class AvatarResultRepository:
    """Database operations for generated HumanInfo results."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, result: AvatarResult) -> AvatarResult:
        """Persist a generated result row."""

        self.session.add(result)
        self.session.flush()
        return result

    def get_by_id(self, result_id: UUID | str) -> AvatarResult | None:
        """Return one result by ID."""

        return self.session.get(AvatarResult, _as_uuid(result_id))

    def find_active_by_image_version(
        self,
        *,
        user_id: UUID | str,
        image_id: UUID | str,
        algorithm_version: str,
        asset_library_version: str,
        schema_version: str,
    ) -> AvatarResult | None:
        """Find reusable active result for an image/version tuple."""

        stmt = select(AvatarResult).where(
            AvatarResult.user_id == _as_uuid(user_id),
            AvatarResult.image_id == _as_uuid(image_id),
            AvatarResult.algorithm_version == algorithm_version,
            AvatarResult.asset_library_version == asset_library_version,
            AvatarResult.schema_version == schema_version,
            AvatarResult.status == AvatarResultStatus.ACTIVE,
        )
        return self.session.scalar(stmt)

    def list_by_user(self, user_id: UUID | str, limit: int = 20, offset: int = 0) -> list[AvatarResult]:
        """List active results for a user, newest first."""

        stmt = (
            select(AvatarResult)
            .where(AvatarResult.user_id == _as_uuid(user_id), AvatarResult.status == AvatarResultStatus.ACTIVE)
            .order_by(AvatarResult.created_at.desc(), AvatarResult.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt))

    def count_by_user(self, user_id: UUID | str) -> int:
        """Count active results for a user."""

        stmt = select(func.count()).select_from(AvatarResult).where(
            AvatarResult.user_id == _as_uuid(user_id),
            AvatarResult.status == AvatarResultStatus.ACTIVE,
        )
        return int(self.session.scalar(stmt) or 0)

    def soft_delete(self, result_id: UUID | str) -> AvatarResult | None:
        """Mark a generated result as deleted."""

        result = self.get_by_id(result_id)
        if result is None:
            return None
        result.status = AvatarResultStatus.DELETED
        result.deleted_at = datetime.now(timezone.utc)
        self.session.flush()
        return result

    def soft_delete_by_image(self, user_id: UUID | str, image_id: UUID | str) -> int:
        """Soft delete active results for a user's image."""

        stmt = select(AvatarResult).where(
            AvatarResult.user_id == _as_uuid(user_id),
            AvatarResult.image_id == _as_uuid(image_id),
            AvatarResult.status == AvatarResultStatus.ACTIVE,
        )
        results = list(self.session.scalars(stmt))
        now = datetime.now(timezone.utc)
        for result in results:
            result.status = AvatarResultStatus.DELETED
            result.deleted_at = now
        self.session.flush()
        return len(results)


def _as_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))
