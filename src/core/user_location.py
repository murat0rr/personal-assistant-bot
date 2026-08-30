"""Геопозиция и часовой пояс основного пользователя (Phase 39, команда
/timezone бота) — до полноценной многопользовательской авторизации (см.
SPEC.md/TECHDEBT.md) расписание планировщика и погода в приложении
управляются только основным владельцем (settings.telegram_user_id), не
каждым авторизованным по паролю отдельно. Запись для любого другого
telegram_user_id тоже сохраняется (на будущее, схема уже
многопользовательская), но на settings/планировщик не влияет."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.core.config import settings
from src.core.db import async_session
from src.models.authorized_user import AuthorizedUser


async def get_owner_location() -> AuthorizedUser | None:
    async with async_session() as session:
        return await session.get(AuthorizedUser, settings.telegram_user_id)


async def apply_stored_timezone() -> None:
    """Вызывать один раз на старте bot- и api-процессов — подтягивает
    сохранённый в БД часовой пояс владельца поверх статичного
    settings.timezone из .env, если он когда-то был установлен командой
    /timezone. settings — обычный (не frozen) pydantic-объект: мутация
    settings.timezone тут же подхватывается везде, где он читается
    (ZoneInfo(settings.timezone) по всему проекту), отдельно прокидывать
    новое значение через каждый вызов не нужно. Бот и API — разные
    процессы с разной памятью, поэтому применяется в обоих отдельно; если
    /timezone сработала без последующего рестарта — API-процесс увидит
    новое значение только после своего следующего рестарта (в этом
    проекте деплой перезапускает оба контейнера, так что расхождение
    живёт недолго)."""
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
