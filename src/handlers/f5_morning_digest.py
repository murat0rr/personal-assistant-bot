from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session
from src.models.task import Task


def build_morning_digest_text(tasks: list[Task], today: date) -> str:
    """Чистая функция форматирования — Task можно создать без сессии БД
    (обычный Python-объект), поэтому тестируется офлайн. due_date — теперь
    timestamp (см. Task), поэтому сравниваем именно дату, не время."""
    active = [t for t in tasks if t.due_date is not None and t.due_date.date() <= today]
    overdue = sorted((t for t in active if t.due_date.date() < today), key=lambda t: t.due_date)
    due_today = [t for t in active if t.due_date.date() == today]

    if not overdue and not due_today:
        return "🌅 Доброе утро! На сегодня активных задач нет."

    lines = ["🌅 Доброе утро!"]
    if overdue:
        lines.append("\n⚠️ Просрочено:")
        lines += [f"— {t.title} ({t.due_date.strftime('%d.%m')})" for t in overdue]
    if due_today:
        lines.append("\n📌 На сегодня:")
        lines += [f"— {t.title}" for t in due_today]
    return "\n".join(lines)


async def build_morning_digest() -> str:
    today = datetime.now(ZoneInfo(settings.timezone)).date()

    async with async_session() as session:
        query = select(Task).where(
            Task.due_date.is_not(None), Task.done.is_(False), Task.archived.is_(False)
        )
        result = await session.execute(query)
        tasks = list(result.scalars().all())

    return build_morning_digest_text(tasks, today)
