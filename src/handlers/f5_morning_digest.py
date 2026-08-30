from datetime import date

from sqlalchemy import select

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


async def build_morning_digest(user_id: int, today: date) -> str:
    # today приходит от вызывающего (Phase 40 — у каждого пользователя
    # своя джоба в своём часовом поясе, см. scheduler/jobs.py), а не
    # считается тут по глобальному settings.timezone.
    async with async_session() as session:
        query = select(Task).where(
            Task.due_date.is_not(None),
            Task.done.is_(False),
            Task.archived.is_(False),
            Task.user_id == user_id,
        )
        result = await session.execute(query)
        tasks = list(result.scalars().all())

    return build_morning_digest_text(tasks, today)
