"""User API for the MVP anonymous-device mode."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db_session
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserProfileResponse

router = APIRouter()


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(session: Session = Depends(get_db_session)) -> UserProfileResponse:
    """Return the default MVP user profile."""

    user = UserRepository(session).get_or_create_by_device_id(settings.default_user_device_id)
    session.commit()
    return UserProfileResponse(
        user_id=str(user.id),
        username=user.username,
        email=user.email,
        created_at=user.created_at,
    )
