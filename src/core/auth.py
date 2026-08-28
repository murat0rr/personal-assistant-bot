from src.core.config import settings


def is_authorized(user_id: int) -> bool:
    return user_id == settings.telegram_user_id
