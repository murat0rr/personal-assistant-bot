from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session
from src.models.authorized_user import AuthorizedUser


def _is_primary_owner(user_id: int) -> bool:
    return user_id == settings.telegram_user_id


async def is_authorized(user_id: int) -> bool:
    # _is_primary_owner — прямой обход БД специально сохранён (Phase 40):
    # если Postgres временно недоступен, основной владелец всё равно
    # может пользоваться ботом. У остальных авторизованных такой
    # страховки нет и не нужно — их доступ и так завязан на БД
    # (AuthorizedUser), недоступность БД для них означает недоступность
    # почти всего остального в приложении в любом случае.
    if _is_primary_owner(user_id):
        return True
    async with async_session() as session:
        return await session.get(AuthorizedUser, user_id) is not None


async def ensure_owner_authorized() -> None:
    """Вызывать на старте bot- и api-процессов (Phase 40) — гарантирует
    строку в authorized_users для основного владельца. is_authorized()
    и раньше пускала его в обход этой таблицы (см. _is_primary_owner
    выше — остаётся для устойчивости к недоступной БД), но с Phase 40
    почти все данные (tasks/habits/... user_id) ссылаются на
    authorized_users по FK — без строки там ничего нельзя было бы
    создать от его имени. Идемпотентно — повторный вызов ничего не
    ломает."""
    async with async_session() as session:
        existing = await session.get(AuthorizedUser, settings.telegram_user_id)
        if existing is None:
            session.add(
                AuthorizedUser(
                    telegram_user_id=settings.telegram_user_id,
                    added_at=datetime.now(ZoneInfo(settings.timezone)),
                )
            )
            await session.commit()


async def list_authorized_user_ids() -> list[int]:
    """Все, кто может пользоваться ботом — владелец в этом списке тоже
    (см. ensure_owner_authorized: строка для него гарантирована на
    старте). Используется планировщиком (Phase 40) — у каждого свои
    персональные джобы, регистрируются по этому списку."""
    async with async_session() as session:
        result = await session.execute(select(AuthorizedUser.telegram_user_id))
        return [row[0] for row in result.all()]
