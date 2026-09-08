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


# Дефолты часа утренней рассылки/вечерней рефлексии (Phase 61) — те
# же значения, что были жёстко зашиты в scheduler/jobs.py::_job_specs
# до этой фазы, теперь только фолбэк, если пользователь не задавал
# свои /morning /evening.
DEFAULT_MORNING_HOUR = 8
DEFAULT_EVENING_HOUR = 21


async def user_schedule_hours(user_id: int) -> tuple[int, int]:
    """(час утренней рассылки, час вечерней рефлексии) — свои, если
    когда-то заданы командами /morning /evening, иначе дефолты выше.
    Используется и планировщиком (register_jobs_for_user/
    reschedule_user_jobs), и /nag (тихий час после рассылки, см.
    handlers/f_task_nag.py) — один источник правды на оба."""
    location = await get_user_location(user_id)
    morning = (
        location.morning_hour
        if location and location.morning_hour is not None
        else DEFAULT_MORNING_HOUR
    )
    evening = (
        location.evening_hour
        if location and location.evening_hour is not None
        else DEFAULT_EVENING_HOUR
    )
    return morning, evening


async def morning_digest_enabled(user_id: int) -> bool:
    """Настройка Mini App (Phase 67) — по умолчанию True (см.
    AuthorizedUser.morning_digest_enabled), отсутствие строки вообще
    (не должно случаться для авторизованного пользователя, но
    защищаемся) тоже трактуем как "включено"."""
    location = await get_user_location(user_id)
    return location.morning_digest_enabled if location else True


async def save_schedule_hour(
    user_id: int, *, morning_hour: int | None = None, evening_hour: int | None = None
) -> None:
    """Сохраняет час утренней рассылки и/или вечерней рефлексии — вызывается
    из handlers/f_schedule.py (/morning, /evening). Обновляет только
    переданные поля, второе остаётся как было. Строка AuthorizedUser
    обычно уже существует (создаётся при авторизации, см. f_auth.py) —
    ветка создания на случай, если её почему-то нет, та же защита, что
    у save_location_for."""
    async with async_session() as session:
        existing = await session.get(AuthorizedUser, user_id)
        if existing is None:
            existing = AuthorizedUser(
                telegram_user_id=user_id, added_at=datetime.now(await user_timezone(user_id))
            )
            session.add(existing)
        if morning_hour is not None:
            existing.morning_hour = morning_hour
        if evening_hour is not None:
            existing.evening_hour = evening_hour
        await session.commit()


async def set_morning_digest_enabled(user_id: int, enabled: bool) -> None:
    """Настройка Mini App (Phase 67) — та же защита "строки может не
    быть", что и save_schedule_hour выше."""
    async with async_session() as session:
        existing = await session.get(AuthorizedUser, user_id)
        if existing is None:
            existing = AuthorizedUser(
                telegram_user_id=user_id, added_at=datetime.now(await user_timezone(user_id))
            )
            session.add(existing)
        existing.morning_digest_enabled = enabled
        await session.commit()


async def guide_banner_shown(user_id: int) -> bool:
    """Плашка "посмотреть гайд" в Mini App (Phase 69) — по умолчанию
    False у новых пользователей (см. AuthorizedUser.guide_banner_shown,
    у уже существующих на момент этой фазы забэкфиллено на True
    миграцией). Отсутствие строки вообще (не должно случаться для
    авторизованного пользователя, но защищаемся) трактуем как "уже
    показывали" — самый безопасный вариант, не навязываем плашку тому,
    о ком нет данных."""
    location = await get_user_location(user_id)
    return location.guide_banner_shown if location else True


async def mark_guide_banner_shown(user_id: int) -> None:
    """Взводится один раз — либо тапом по плашке, либо крестиком (см.
    index.html) — та же защита "строки может не быть", что и
    save_schedule_hour выше."""
    async with async_session() as session:
        existing = await session.get(AuthorizedUser, user_id)
        if existing is None:
            existing = AuthorizedUser(
                telegram_user_id=user_id, added_at=datetime.now(await user_timezone(user_id))
            )
            session.add(existing)
        existing.guide_banner_shown = True
        await session.commit()


async def questions_topic_id(user_id: int) -> int | None:
    """id темы "Вопросы" в личном чате этого пользователя (Phase 81,
    Threaded Mode) — None, если ещё не создавалась (см.
    core/topics.py::get_or_create_questions_topic)."""
    location = await get_user_location(user_id)
    return location.questions_topic_id if location else None


async def save_questions_topic_id(user_id: int, topic_id: int) -> None:
    """Та же защита "строки может не быть", что и save_schedule_hour
    выше."""
    async with async_session() as session:
        existing = await session.get(AuthorizedUser, user_id)
        if existing is None:
            existing = AuthorizedUser(
                telegram_user_id=user_id, added_at=datetime.now(await user_timezone(user_id))
            )
            session.add(existing)
        existing.questions_topic_id = topic_id
        await session.commit()


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
