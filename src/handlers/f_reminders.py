import calendar
import logging
from datetime import date, datetime
from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.db import async_session
from src.integrations.claude_client import ReminderPlan, parse_reminder
from src.integrations.geocoding import geocode
from src.models.reminder import Reminder

_DEFAULT_RADIUS_M = 200

logger = logging.getLogger(__name__)

router = Router()

_WEEKDAY_NAMES = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def _plan_to_value(plan: ReminderPlan) -> dict:
    if plan.schedule_kind == "once":
        return {"date": plan.reminder_date.isoformat() if plan.reminder_date else None}
    if plan.schedule_kind == "monthly_day":
        return {"day": plan.day_of_month}
    if plan.schedule_kind == "weekly_day":
        return {"weekday": plan.weekday}
    if plan.schedule_kind == "location":
        # Координаты подставляются отдельно в handle_new_reminder — здесь
        # только place_name, геокодирование асинхронное и может не найти место.
        return {"place_name": plan.place_name}
    return {"interval_days": plan.interval_days}


def _describe_schedule(kind: str, value: dict) -> str:
    if kind == "once":
        return f"разово, {value.get('date')}"
    if kind == "monthly_day":
        day = value.get("day")
        return "каждый месяц в последний день" if day == 32 else f"каждый месяц {day} числа"
    if kind == "weekly_day":
        weekday = value.get("weekday")
        name = _WEEKDAY_NAMES[weekday] if weekday is not None and 0 <= weekday <= 6 else "?"
        return f"каждую неделю в {name}"
    if kind == "interval_days":
        return f"раз в {value.get('interval_days')} дн."
    if kind == "location":
        return f"когда буду рядом с {value.get('place_name')}"
    return kind


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между двумя точками на сфере (формула гаверсинуса), в метрах."""
    earth_radius_m = 6_371_000
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))


def _is_within_radius(reminder: Reminder, lat: float, lon: float) -> bool:
    value = reminder.schedule_value
    if "lat" not in value or "lon" not in value:
        return False
    distance = _haversine_m(value["lat"], value["lon"], lat, lon)
    return distance <= value.get("radius_m", _DEFAULT_RADIUS_M)


def _is_due(reminder: Reminder, today: date) -> bool:
    if reminder.last_fired_date == today:
        return False

    value = reminder.schedule_value
    kind = reminder.schedule_kind

    if kind == "once":
        return value.get("date") == today.isoformat()
    if kind == "monthly_day":
        day = value.get("day")
        if day == 32:
            last_day = calendar.monthrange(today.year, today.month)[1]
            return today.day == last_day
        return today.day == day
    if kind == "weekly_day":
        return today.weekday() == value.get("weekday")
    if kind == "interval_days":
        anchor = reminder.last_fired_date or reminder.created_at.date()
        interval = value.get("interval_days") or 1
        return (today - anchor).days % interval == 0

    return False


async def handle_new_reminder(message: Message, text: str) -> None:
    try:
        today = datetime.now(ZoneInfo(settings.timezone)).date()
        plan = await parse_reminder(text, today)
    except Exception:
        logger.exception("Не удалось разобрать напоминание: %r", text)
        await message.answer("Не получилось разобрать напоминание, попробуй ещё раз.")
        return

    value = _plan_to_value(plan)

    if plan.schedule_kind == "location":
        coords = await geocode(plan.place_name or "")
        if coords is None:
            await message.answer("Не нашёл такое место, опиши точнее (адрес, район, город).")
            return
        lat, lon = coords
        value = {**value, "lat": lat, "lon": lon, "radius_m": _DEFAULT_RADIUS_M}

    async with async_session() as session:
        session.add(
            Reminder(
                text=plan.text,
                schedule_kind=plan.schedule_kind,
                schedule_value=value,
                created_at=datetime.now(ZoneInfo(settings.timezone)),
            )
        )
        await session.commit()

    await message.answer(
        f"Готово, буду напоминать: «{plan.text}» ({_describe_schedule(plan.schedule_kind, value)})"
    )


async def check_reminders(bot: Bot) -> None:
    today = datetime.now(ZoneInfo(settings.timezone)).date()

    async with async_session() as session:
        result = await session.execute(select(Reminder))
        due = [r for r in result.scalars().all() if _is_due(r, today)]

        for reminder in due:
            await bot.send_message(chat_id=settings.telegram_user_id, text=f"🔔 {reminder.text}")
            if reminder.schedule_kind == "once":
                await session.delete(reminder)
            else:
                reminder.last_fired_date = today

        await session.commit()

    logger.info("Проверка напоминаний: сработало %s", len(due))


async def check_location_reminders(bot: Bot, lat: float, lon: float) -> None:
    async with async_session() as session:
        result = await session.execute(select(Reminder).where(Reminder.schedule_kind == "location"))
        matched = [r for r in result.scalars().all() if _is_within_radius(r, lat, lon)]

        for reminder in matched:
            await bot.send_message(chat_id=settings.telegram_user_id, text=f"🔔 {reminder.text}")
            # Гео-напоминания одноразовые — сработало и удалилось, как "once".
            await session.delete(reminder)

        await session.commit()

    if matched:
        logger.info("Гео-напоминания: сработало %s", len(matched))


@router.message(Command("reminders"))
async def list_reminders_command(message: Message) -> None:
    if not message.from_user or not is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    async with async_session() as session:
        result = await session.execute(select(Reminder))
        reminders = result.scalars().all()

    if not reminders:
        await message.answer("Напоминаний нет.")
        return

    for reminder in reminders:
        description = _describe_schedule(reminder.schedule_kind, reminder.schedule_value)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Удалить", callback_data=f"reminder_del:{reminder.id}"
                    )
                ]
            ]
        )
        await message.answer(f"🔔 {reminder.text} — {description}", reply_markup=keyboard)


@router.callback_query(F.data.startswith("reminder_del:"))
async def delete_reminder_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if not callback.data:
        return

    reminder_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        reminder = await session.get(Reminder, reminder_id)
        if reminder is not None:
            await session.delete(reminder)
            await session.commit()

    await callback.answer("Удалено")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
