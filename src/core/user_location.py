"""Геопозиция и часовой пояс пользователей (Phase 39, команда /timezone
бота; Phase 40 — стало по-настоящему многопользовательским). Каждый
авторизованный пользователь может задать свою геопозицию — используется
для его личной погоды в дайджесте и его личного часового пояса
(планировщик, Phase 40 — у каждого свои джобы, см. scheduler/jobs.py)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.core.config import settings
from src.core.db import async_session
from src.models.authorized_user import AuthorizedUser


async def get_user_location(user_id: int) -> AuthorizedUser | None:
    async with async_session() as session:
        return await session.get(AuthorizedUser, user_id)


async def user_timezone(user_id: int) -> ZoneInfo:
    """Часовой пояс конкретного пользователя (Phase 40) — свой, если
    когда-то задан командой /timezone, иначе дефолт из .env
    (settings.timezone — тот же, что применяется владельцу при старте
    процесса, см. apply_stored_timezone). Используется везде, где
    планировщик или хендлер должны знать "какой сегодня день" ИМЕННО
    для этого пользователя, а не глобально."""
    location = await get_user_location(user_id)
    return ZoneInfo(location.timezone if location and location.timezone else settings.timezone)


async def user_today(user_id: int) -> date:
    return datetime.now(await user_timezone(user_id)).date()


async def get_owner_location() -> AuthorizedUser | None:
    """Частный случай get_user_location — основной владелец, чей часовой
    пояс по умолчанию применяется к settings.timezone на старте процесса
    (см. apply_stored_timezone)."""
    return await get_user_location(settings.telegram_user_id)


async def apply_stored_timezone() -> None:
    """Вызывать один раз на старте bot- и api-процессов — подтягивает
    сохранённый в БД часовой пояс ВЛАДЕЛЬЦА поверх статичного
    settings.timezone из .env (дефолт для мест, которые ещё не стали
    per-user — например day-boundary внутри самого /timezone до первого
    успешного вызова). settings — обычный (не frozen) pydantic-объект:
    мутация settings.timezone тут же подхватывается везде, где он
    читается. Бот и API — разные процессы с разной памятью, поэтому
    применяется в обоих отдельно; если /timezone сработала без
    последующего рестарта — API-процесс увидит новое значение только
    после своего следующего рестарта (в этом проекте деплой
    перезапускает оба контейнера, так что расхождение живёт недолго)."""
    owner = await get_owner_location()
    if owner and owner.timezone:
        settings.timezone = owner.timezone


async def save_location_for(
    telegram_user_id: int,
    latitude: float,
    longitude: float,
    timezone: str,
    location_label: str | None,
) -> None:
    async with async_session() as session:
        existing = await session.get(AuthorizedUser, telegram_user_id)
        if existing is None:
            existing = AuthorizedUser(
                telegram_user_id=telegram_user_id,
                added_at=datetime.now(ZoneInfo(timezone)),
            )
            session.add(existing)
        existing.latitude = latitude
        existing.longitude = longitude
        existing.timezone = timezone
        existing.location_label = location_label
        await session.commit()
