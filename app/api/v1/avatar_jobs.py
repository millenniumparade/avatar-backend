"""Avatar generation job API."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile

from app.schemas.avatar_job import AvatarJobCreateResponse, AvatarJobStatusResponse
from app.services.avatar_job_service import AvatarJobService, get_avatar_job_service

router = APIRouter()


@router.post("", response_model=AvatarJobCreateResponse)
async def create_avatar_job(
    image: Annotated[UploadFile, File(description="User face image.")],
    client_request_id: Annotated[str | None, Form(description="Optional client idempotency ID.")] = None,
    x_device_id: Annotated[
        str | None,
        Header(description="Anonymous device/user ID. Use different values to simulate different users."),
    ] = None,
    service: AvatarJobService = Depends(get_avatar_job_service),
) -> AvatarJobCreateResponse:
    """Create an async avatar generation job."""

    if x_device_id:
        service.device_id = x_device_id
    return await service.create_job(image=image, client_request_id=client_request_id)


@router.get("/{job_id}", response_model=AvatarJobStatusResponse)
async def get_avatar_job(
    job_id: str,
    service: AvatarJobService = Depends(get_avatar_job_service),
) -> AvatarJobStatusResponse:
    """Return job status, progress, result ID, or failure reason."""

    return await service.get_job_status(job_id=job_id)
