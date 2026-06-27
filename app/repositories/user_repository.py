"""Repository for users."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Database operations for users and anonymous devices."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_by_device_id(self, device_id: str) -> User:
        """Return an existing anonymous device user or create one."""

        stmt = select(User).where(User.device_id == device_id)
        user = self.session.scalar(stmt)
        if user is not None:
            return user

        user = User(device_id=device_id)
        self.session.add(user)
        self.session.flush()
        return user
