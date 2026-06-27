"""MVP security helpers."""

from app.core.config import settings


def get_current_user_id() -> str:
    """Return the default anonymous device ID used by the MVP."""

    return settings.default_user_device_id
