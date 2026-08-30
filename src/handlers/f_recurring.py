import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import Message

from src.core.config import settings
from src.core.recurring_tasks import create_rule
from src.integrations.claude_client import ReminderPlan, parse_reminder

logger = logging.getLogger(__name__)

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
    if plan.schedule_kind == "monthly_day":
        return {"day": plan.day_of_month}
    if plan.schedule_kind == "weekly_day":
        return {"weekday": plan.weekday}
    return {"interval_days": plan.interval_days}


def _describe_schedule(kind: str, value: dict) -> str:
    if kind == "monthly_day":
        day = value.get("day")
        return "каждый месяц в последний день" if day == 32 else f"каждый месяц {day} числа"
    if kind == "weekly_day":
        weekday = value.get("weekday")
        name = _WEEKDAY_NAMES[weekday] if weekday is not None and 0 <= weekday <= 6 else "?"
        return f"каждую неделю в {name}"
    return f"раз в {value.get('interval_days')} дн."


async def handle_new_recurring_task(message: Message, text: str) -> None:
    """Свободный текст ("каждый понедельник разгрести почту") — Claude
    вычленяет паттерн (переиспользуем parse_reminder, схема разбора
    совпадает с напоминалками, см. f_reminders.py), из результата
    складывается RecurringTaskRule. Реальные Task-строки появляются
    только на факт наступившего дня — см.
    scheduler/jobs.py::_materialize_recurring_tasks_job."""
    try:
        today = datetime.now(ZoneInfo(settings.timezone)).date()
        plan = await parse_reminder(text, today)
    except Exception:
        logger.exception("Не удалось разобрать повторяющуюся задачу: %r", text)
        await message.answer("Не получилось разобрать, попробуй ещё раз.")
        return

    if plan.schedule_kind in ("once", "location"):
        await message.answer(
            "Это не похоже на повторяющуюся задачу — опиши, как часто её "
            "делать (например «каждый понедельник», «раз в 3 дня», "
            "«5 числа каждого месяца»)."
        )
        return

    value = _plan_to_value(plan)
    await create_rule(plan.text, plan.schedule_kind, value)
    schedule_desc = _describe_schedule(plan.schedule_kind, value)
    await message.answer(f"Готово, буду создавать задачу: «{plan.text}» ({schedule_desc})")
