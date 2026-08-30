"""Команда /timezone (Phase 39) — определяет часовой пояс и координаты
пользователя по живой геопозиции из Telegram, вместо статичного
settings.timezone/settings.weather_city из .env. См. src/core/user_location.py
за тем, как это применяется к остальному приложению, и SPEC.md за
обоснованием ограничения "работает только на основного владельца, пока
нет полноценной многопользовательской авторизации"."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.storage.base import BaseStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.user_location import save_location_for
from src.integrations.geocoding import resolve_timezone, reverse_geocode_label
from src.scheduler.jobs import reschedule_for_timezone

logger = logging.getLogger(__name__)

router = Router()

_LOCATION_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


@router.message(Command("timezone"))
async def handle_timezone_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return
    await message.answer(
        "Пришли геопозицию (кнопка ниже) — определю часовой пояс и место "
        "для погоды по координатам.",
        reply_markup=_LOCATION_KEYBOARD,
    )


@router.message(F.location)
async def handle_location(
    message: Message, bot: Bot, scheduler: AsyncIOScheduler, storage: BaseStorage
) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        return
    if not message.location:
        return

    lat, lon = message.location.latitude, message.location.longitude
    tz_name = await resolve_timezone(lat, lon)
    if not tz_name:
        await message.answer(
            "Не получилось определить часовой пояс по этим координатам — "
            "попробуй ещё раз чуть позже.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    label = await reverse_geocode_label(lat, lon)
    await save_location_for(message.from_user.id, lat, lon, tz_name, label)

    is_owner = message.from_user.id == settings.telegram_user_id
    where = f" ({label})" if label else ""
    if is_owner:
        # Основной владелец — его часовой пояс управляет расписанием
        # планировщика и погодой во всём приложении (см.
        # src/core/user_location.py). Применяем немедленно, без
        # перезапуска процесса: settings — обычный мутируемый объект, а
        # уже зарегистрированные джобы пересобираются явно (см.
        # reschedule_for_timezone — CronTrigger резолвит tzinfo один раз
        # при создании, менять scheduler.timezone задним числом бесполезно).
        settings.timezone = tz_name
        reschedule_for_timezone(scheduler, bot, storage, tz_name)
        logger.info("Часовой пояс владельца обновлён: %s%s", tz_name, where)
        text = f"Готово! Часовой пояс: {tz_name}{where}. Расписание уже пересчитано."
    else:
        # Пока нет полноценной многопользовательской авторизации (см.
        # SPEC.md) — сохраняем на будущее, но ни на расписание, ни на
        # погоду это пока не влияет, честно предупреждаем об этом.
        text = (
            f"Сохранил: {tz_name}{where}. Но пока часовой пояс и расписание "
            "бота настраивает только основной пользователь — на твои "
            "напоминания это ещё не влияет."
        )

    await message.answer(text, reply_markup=ReplyKeyboardRemove())
