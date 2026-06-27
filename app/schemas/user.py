"""用户 API schema。"""

from datetime import datetime

from pydantic import BaseModel


class UserProfileResponse(BaseModel):
    """当前用户资料响应。"""

    user_id: str
    username: str | None = None
    email: str | None = None
    created_at: datetime | None = None

