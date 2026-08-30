"""Команда /timezone (Phase 39, стала по-настоящему многопользовательской
в Phase 40) — определяет часовой пояс и координаты пользователя по живой
геопозиции из Telegram, вместо статичного settings.timezone/
settings.weather_city из .env. См. src/core/user_location.py за тем, как
это применяется к остальному приложению."""

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
    user_id = message.from_user.id

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
    await save_location_for(user_id, lat, lon, tz_name, label)

    # Часовой пояс каждого пользователя управляет ЕГО ЛИЧНЫМ расписанием
    # (Phase 40 — у каждого свои джобы) и его личной погодой — применяем
    # сразу, без перезапуска процесса: reschedule_for_timezone пересобирает
    # именно его джобы (CronTrigger резолвит tzinfo один раз при
    # создании, просто поменять что-то задним числом нельзя).
    if user_id == settings.telegram_user_id:
        # Основной владелец — его зона ещё и дефолт settings.timezone для
        # всего, что пока не стало per-user (см. user_location.py).
        # settings — обычный мутируемый pydantic-объект, применяется
        # немедленно, без правок в каждом месте использования.
        settings.timezone = tz_name
    await reschedule_for_timezone(scheduler, bot, storage, user_id, tz_name)
    logger.info("Часовой пояс обновлён (%s): %s", user_id, tz_name)

    where = f" ({label})" if label else ""
    await message.answer(
        f"Готово! Часовой пояс: {tz_name}{where}. Расписание уже пересчитано.",
        reply_markup=ReplyKeyboardRemove(),
    )
