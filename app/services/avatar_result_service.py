"""Avatar result business service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AvatarError, ErrorCode
from app.db.session import get_db_session
from app.repositories.avatar_result_repository import AvatarResultRepository
from app.repositories.user_repository import UserRepository
from app.schemas.avatar_result import AvatarResultListResponse, AvatarResultResponse, AvatarResultSummary


class AvatarResultService:
    """Read, list, and soft-delete generated HumanInfo results."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def get_result(self, result_id: str) -> AvatarResultResponse:
        """Return one active result."""

        result = AvatarResultRepository(self.session).get_by_id(result_id)
        if result is None or result.status != "active":
            raise AvatarError(code=ErrorCode.NOT_FOUND, message="Avatar result was not found.", status_code=404)

        return AvatarResultResponse(
            result_id=str(result.id),
            schema_version=result.schema_version,
            algorithm_version=result.algorithm_version,
            asset_library_version=result.asset_library_version,
            human_info=result.result_json,
        )

    async def list_results(self, *, limit: int = 20, offset: int = 0) -> AvatarResultListResponse:
        """List active results for the default MVP user."""

        user = UserRepository(self.session).get_or_create_by_device_id(settings.default_user_device_id)
        repo = AvatarResultRepository(self.session)
        results = repo.list_by_user(user.id, limit=limit, offset=offset)
        total = repo.count_by_user(user.id)
        items = [
            AvatarResultSummary(
                result_id=str(result.id),
                job_id=str(result.job_id),
                preview_url=result.preview_image_key,
                created_at=result.created_at,
            )
            for result in results
        ]
        return AvatarResultListResponse(items=items, total=total, limit=limit, offset=offset)

    async def delete_result(self, result_id: str) -> None:
        """Soft-delete one result."""

        result = AvatarResultRepository(self.session).soft_delete(result_id)
        if result is None:
            raise AvatarError(code=ErrorCode.NOT_FOUND, message="Avatar result was not found.", status_code=404)
        self.session.commit()


def get_avatar_result_service(session: Session = Depends(get_db_session)) -> AvatarResultService:
    """Return a request-scoped result service."""

    return AvatarResultService(session=session)
