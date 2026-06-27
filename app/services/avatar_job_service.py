"""Avatar job orchestration service."""

from __future__ import annotations

import hashlib
import tempfile
from uuid import uuid4

from fastapi import Depends, UploadFile
from PIL import UnidentifiedImageError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AvatarError, ErrorCode
from app.db.session import get_db_session
from app.models.avatar_job import AvatarJob, AvatarJobStatus
from app.repositories.avatar_job_repository import AvatarJobRepository
from app.repositories.avatar_result_repository import AvatarResultRepository
from app.repositories.outbox_event_repository import OutboxEventRepository
from app.repositories.uploaded_image_repository import UploadedImageRepository
from app.repositories.user_repository import UserRepository
from app.schemas.avatar_job import AvatarJobCreateResponse, AvatarJobStatusResponse
from app.services.rate_limit_service import ActiveJobAdmission, RateLimitService
from app.services.storage_service import StorageService, get_storage_service
from app.utils.image_utils import read_image_size_from_stream, validate_image_extension


class AvatarJobService:
    """Validate uploads, reuse cached results, create jobs, and enqueue workers."""

    def __init__(
        self,
        session: Session,
        storage_service: StorageService,
        *,
        enqueue_tasks: bool = True,
        device_id: str | None = None,
        rate_limit_service: RateLimitService | None = None,
    ) -> None:
        self.session = session
        self.storage_service = storage_service
        self.enqueue_tasks = enqueue_tasks
        self.device_id = device_id or settings.default_user_device_id
        self.rate_limit_service = rate_limit_service or RateLimitService()

    async def create_job(self, image: UploadFile, client_request_id: str | None = None) -> AvatarJobCreateResponse:
        """Create an async avatar generation job."""

        user = UserRepository(self.session).get_or_create_by_device_id(self.device_id)
        job_repo = AvatarJobRepository(self.session)
        await self.rate_limit_service.check_upload_rate(str(user.id))
        admission = await self.rate_limit_service.acquire_job_admission(str(user.id))

        try:
            self._reject_existing_active_job(job_repo, user.id, admission)
            return await self._create_admitted_job(
                image=image,
                user_id=user.id,
                job_repo=job_repo,
                admission=admission,
            )
        except IntegrityError:
            self.session.rollback()
            self.rate_limit_service.release_job_admission_best_effort(admission)
            self._raise_active_job_exists(job_repo, user.id)
        except Exception:
            await self.rate_limit_service.release_job_admission(admission)
            raise

    async def _create_admitted_job(
        self,
        *,
        image: UploadFile,
        user_id,
        job_repo: AvatarJobRepository,
        admission: ActiveJobAdmission,
    ) -> AvatarJobCreateResponse:
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as upload_stream:
            image_hash, file_size, width, height = await self._stream_and_validate_upload(image, upload_stream)

            existing_image = UploadedImageRepository(self.session).find_active_by_hash(user_id, image_hash)
            image_id = str(existing_image.id) if existing_image is not None else str(uuid4())
            if existing_image is not None:
                image_key = existing_image.original_image_key
            else:
                upload_stream.seek(0)
                image_key = await self.storage_service.save_upload_stream(
                    user_id=str(user_id),
                    image_id=image_id,
                    stream=upload_stream,
                    filename=image.filename,
                    content_type=image.content_type,
                )
            uploaded_image, _ = UploadedImageRepository(self.session).get_or_create_by_hash(
                user_id=user_id,
                image_hash=image_hash,
                original_image_key=image_key,
                mime_type=image.content_type or "application/octet-stream",
                file_size=file_size,
                width=width,
                height=height,
            )

        result_repo = AvatarResultRepository(self.session)
        cached_result = result_repo.find_active_by_image_version(
            user_id=user_id,
            image_id=uploaded_image.id,
            algorithm_version=settings.algorithm_version,
            asset_library_version=settings.asset_library_version,
            schema_version=settings.result_schema_version,
        )
        if cached_result is not None:
            job = job_repo.create(
                AvatarJob(
                    user_id=user_id,
                    image_id=uploaded_image.id,
                    status=AvatarJobStatus.SUCCEEDED,
                    result_id=cached_result.id,
                    cache_hit=True,
                    progress=100,
                    algorithm_version=settings.algorithm_version,
                    asset_library_version=settings.asset_library_version,
                    schema_version=settings.result_schema_version,
                )
            )
            self.session.commit()
            await self.rate_limit_service.release_job_admission(admission)
            return AvatarJobCreateResponse(job_id=str(job.id), status=job.status, estimated_wait_seconds=0)

        job = job_repo.create(
            AvatarJob(
                user_id=user_id,
                image_id=uploaded_image.id,
                status=AvatarJobStatus.QUEUED,
                progress=0,
                algorithm_version=settings.algorithm_version,
                asset_library_version=settings.asset_library_version,
                schema_version=settings.result_schema_version,
            )
        )
        self.rate_limit_service.bind_active_job_best_effort(admission, str(job.id))
        celery_task_id = f"avatar-job-{job.id}"

        if self.enqueue_tasks:
            job_repo.set_celery_task_id(job.id, celery_task_id)
            OutboxEventRepository(self.session).create_avatar_job_event(
                job_id=job.id,
                task_id=celery_task_id,
                queue=settings.celery_gpu_queue,
            )

        self.session.commit()
        return AvatarJobCreateResponse(job_id=str(job.id), status=job.status, estimated_wait_seconds=8)

    def _reject_existing_active_job(
        self,
        job_repo: AvatarJobRepository,
        user_id,
        admission: ActiveJobAdmission,
    ) -> None:
        active_job = job_repo.find_active_by_user(user_id)
        if active_job is None:
            return
        if self.rate_limit_service.bind_active_job_best_effort(admission, str(active_job.id)):
            admission.active_lock_acquired = False
        raise AvatarError(
            code=ErrorCode.ACTIVE_JOB_EXISTS,
            message=f"User already has active avatar job {active_job.id}.",
            status_code=429,
        )

    def _raise_active_job_exists(self, job_repo: AvatarJobRepository, user_id) -> None:
        active_job = job_repo.find_active_by_user(user_id)
        if active_job is not None:
            self.rate_limit_service.remember_active_job_best_effort(str(user_id), str(active_job.id))
            raise AvatarError(
                code=ErrorCode.ACTIVE_JOB_EXISTS,
                message=f"User already has active avatar job {active_job.id}.",
                status_code=429,
            )
        raise AvatarError(
            code=ErrorCode.ACTIVE_JOB_EXISTS,
            message="User already has an active avatar job.",
            status_code=429,
        )

    async def get_job_status(self, job_id: str) -> AvatarJobStatusResponse:
        """Return the current job status for client polling."""

        job = AvatarJobRepository(self.session).get_by_id(job_id)
        if job is None:
            raise AvatarError(code=ErrorCode.NOT_FOUND, message="Avatar job was not found.", status_code=404)

        return AvatarJobStatusResponse(
            job_id=str(job.id),
            status=job.status,
            progress=job.progress,
            stage=job.current_stage,
            result_id=str(job.result_id) if job.result_id else None,
            error_code=job.error_code,
            message=job.error_message,
        )

    async def _stream_and_validate_upload(self, image: UploadFile, output) -> tuple[str, int, int, int]:
        if not validate_image_extension(image.filename or "", settings.allowed_image_extensions):
            raise AvatarError(
                code=ErrorCode.INVALID_IMAGE_FORMAT,
                message="Only jpg, jpeg, png, and webp images are supported.",
                status_code=400,
            )

        digest = hashlib.sha256()
        total_bytes = 0
        max_bytes = settings.max_image_size_mb * 1024 * 1024
        await image.seek(0)
        while chunk := await image.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise AvatarError(
                    code=ErrorCode.IMAGE_TOO_LARGE,
                    message=f"Upload image exceeds {settings.max_image_size_mb} MB.",
                    status_code=413,
                )
            digest.update(chunk)
            output.write(chunk)
        await image.seek(0)
        output.seek(0)
        width, height = self._read_upload_dimensions(output)
        output.seek(0)
        return digest.hexdigest(), total_bytes, width, height

    def _read_upload_dimensions(self, stream) -> tuple[int, int]:
        try:
            width, height = read_image_size_from_stream(stream)
        except UnidentifiedImageError as exc:
            raise AvatarError(
                code=ErrorCode.INVALID_IMAGE_FORMAT,
                message="Uploaded file is not a readable image.",
                status_code=400,
            ) from exc

        if width > settings.max_image_width or height > settings.max_image_height:
            raise AvatarError(
                code=ErrorCode.IMAGE_RESOLUTION_TOO_HIGH,
                message=(
                    "Upload image resolution is too high for API transfer. "
                    f"Maximum is {settings.max_image_width}x{settings.max_image_height}."
                ),
                status_code=413,
            )
        return width, height


def get_avatar_job_service(
    session: Session = Depends(get_db_session),
    storage_service: StorageService = Depends(get_storage_service),
) -> AvatarJobService:
    """Return a request-scoped avatar job service."""

    return AvatarJobService(session=session, storage_service=storage_service)
