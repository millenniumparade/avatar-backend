"""Avatar result API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AvatarResultResponse(BaseModel):
    """Persisted HumanInfo payload plus backend version metadata."""

    result_id: str
    schema_version: str
    algorithm_version: str
    asset_library_version: str
    human_info: dict


class AvatarResultSummary(BaseModel):
    """History item summary."""

    result_id: str
    job_id: str
    preview_url: str | None = None
    created_at: datetime


class AvatarResultListResponse(BaseModel):
    """Paginated result list."""

    items: list[AvatarResultSummary]
    total: int
    limit: int
    offset: int
