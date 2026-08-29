from src.core.config import settings
from src.core.db import async_session
from src.models.authorized_user import AuthorizedUser


def _is_primary_owner(user_id: int) -> bool:
    return user_id == settings.telegram_user_id


async def is_authorized(user_id: int) -> bool:
    if _is_primary_owner(user_id):
        return True
    async with async_session() as session:
        return await session.get(AuthorizedUser, user_id) is not None
