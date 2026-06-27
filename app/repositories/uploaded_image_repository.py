"""Repository for uploaded_images."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.uploaded_image import ImageStatus, UploadedImage


class UploadedImageRepository:
    """Database operations for user-uploaded images."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, image: UploadedImage) -> UploadedImage:
        """Persist a new uploaded image row."""

        self.session.add(image)
        self.session.flush()
        return image

    def get_by_id(self, image_id: UUID | str) -> UploadedImage | None:
        """Return one image by ID."""

        return self.session.get(UploadedImage, _as_uuid(image_id))

    def find_active_by_hash(self, user_id: UUID | str, image_hash: str) -> UploadedImage | None:
        """Find an active image for the same user and content hash."""

        stmt = select(UploadedImage).where(
            UploadedImage.user_id == _as_uuid(user_id),
            UploadedImage.image_hash == image_hash,
            UploadedImage.status == ImageStatus.ACTIVE,
        )
        return self.session.scalar(stmt)

    def get_or_create_by_hash(
        self,
        *,
        user_id: UUID | str,
        image_hash: str,
        original_image_key: str,
        mime_type: str,
        file_size: int,
        thumbnail_key: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> tuple[UploadedImage, bool]:
        """Return active image by hash or create it."""

        existing = self.find_active_by_hash(user_id=user_id, image_hash=image_hash)
        if existing is not None:
            return existing, False

        image = UploadedImage(
            user_id=_as_uuid(user_id),
            image_hash=image_hash,
            original_image_key=original_image_key,
            thumbnail_key=thumbnail_key,
            mime_type=mime_type,
            file_size=file_size,
            width=width,
            height=height,
            status=ImageStatus.ACTIVE,
        )
        return self.create(image), True

    def list_by_user(self, user_id: UUID | str, limit: int = 20, offset: int = 0) -> list[UploadedImage]:
        """List active images for a user, newest first."""

        stmt = (
            select(UploadedImage)
            .where(UploadedImage.user_id == _as_uuid(user_id), UploadedImage.status == ImageStatus.ACTIVE)
            .order_by(UploadedImage.created_at.desc(), UploadedImage.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt))

    def soft_delete(self, image_id: UUID | str) -> UploadedImage | None:
        """Mark one uploaded image as deleted."""

        image = self.get_by_id(image_id)
        if image is None:
            return None
        image.status = ImageStatus.DELETED
        image.deleted_at = datetime.now(timezone.utc)
        self.session.flush()
        return image


def _as_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))
