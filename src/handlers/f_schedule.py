"""Команды /morning и /evening (Phase 61) — настраивают час утренней
рассылки и час вечерней рефлексии дневника за пользователя, вместо
жёстко зашитых 8:00/21:00 (см. src/scheduler/jobs.py::_job_specs).
Тот же паттерн, что /nag (Phase 59) — без FSM, команда → инлайн-
клавиатура часов → callback_query сохраняет и пересобирает джобы через
reschedule_user_jobs (тот же пересборщик, что у /timezone)."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.storage.base import BaseStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.auth import is_authorized
from src.core.user_location import save_schedule_hour
from src.scheduler.jobs import reschedule_user_jobs

logger = logging.getLogger(__name__)

router = Router()

# Разумные бытовые рамки — дёшево расширить, если понадобится.
_MORNING_HOURS = range(6, 12)  # 6..11
_EVENING_HOURS = range(18, 24)  # 18..23


def _hours_keyboard(hours: range, prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(h), callback_data=f"{prefix}:{h}") for h in hours]
        ]
    )


@router.message(Command("morning"))
async def set_morning_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return
    await message.answer(
        "В котором часу присылать утреннюю рассылку?",
        reply_markup=_hours_keyboard(_MORNING_HOURS, "morning_hour"),
    )


@router.message(Command("evening"))
async def set_evening_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return
    await message.answer(
        "В котором часу начинать вечернюю рефлексию?",
        reply_markup=_hours_keyboard(_EVENING_HOURS, "evening_hour"),
    )


@router.callback_query(F.data.startswith("morning_hour:"))
async def set_morning_hour(
    callback: CallbackQuery, bot: Bot, scheduler: AsyncIOScheduler, storage: BaseStorage
) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if not callback.data:
        return
    hour = int(callback.data.split(":")[1])
    if hour not in _MORNING_HOURS:
        await callback.answer()
        return

    user_id = callback.from_user.id
    await save_schedule_hour(user_id, morning_hour=hour)
    await reschedule_user_jobs(scheduler, bot, storage, user_id)
    logger.info("Час утренней рассылки обновлён (%s): %s", user_id, hour)

    await callback.answer("Готово")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Утренняя рассылка теперь в {hour}:00.")


@router.callback_query(F.data.startswith("evening_hour:"))
async def set_evening_hour(
    callback: CallbackQuery, bot: Bot, scheduler: AsyncIOScheduler, storage: BaseStorage
) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if not callback.data:
        return
    hour = int(callback.data.split(":")[1])
    if hour not in _EVENING_HOURS:
        await callback.answer()
        return

    user_id = callback.from_user.id
    await save_schedule_hour(user_id, evening_hour=hour)
    await reschedule_user_jobs(scheduler, bot, storage, user_id)
    logger.info("Час вечерней рефлексии обновлён (%s): %s", user_id, hour)

    await callback.answer("Готово")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Вечерняя рефлексия теперь в {hour}:00.")
