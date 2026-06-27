"""Avatar generation result API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.schemas.avatar_result import AvatarResultListResponse, AvatarResultResponse
from app.services.avatar_result_service import AvatarResultService, get_avatar_result_service

router = APIRouter()


@router.get("", response_model=AvatarResultListResponse)
async def list_avatar_results(
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum number of results to return.")] = 20,
    offset: Annotated[int, Query(ge=0, description="Number of results to skip.")] = 0,
    service: AvatarResultService = Depends(get_avatar_result_service),
) -> AvatarResultListResponse:
    """List active avatar results with offset pagination."""

    return await service.list_results(limit=limit, offset=offset)


@router.get("/{result_id}", response_model=AvatarResultResponse)
async def get_avatar_result(
    result_id: str,
    service: AvatarResultService = Depends(get_avatar_result_service),
) -> AvatarResultResponse:
    """Return one HumanInfo JSON result."""

    return await service.get_result(result_id=result_id)


@router.delete("/{result_id}", status_code=204)
async def delete_avatar_result(
    result_id: str,
    service: AvatarResultService = Depends(get_avatar_result_service),
) -> None:
    """Soft-delete an avatar result."""

    await service.delete_result(result_id=result_id)
