import calendar
from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.task import Task


async def month_events(user_id: int, year: int, month: int) -> dict[str, list[str]]:
    """Для месячного календаря в Mini App (Phase 26) — только задачи-
    события (priority="event"), не все задачи: требование явно про
    события, не про общую загрузку дня (для неё есть график месяца в
    аналитике). Отдаём сами заголовки (Phase 29) — плитка дня показывает
    текст события, не просто точку/иконку."""
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    async with async_session() as session:
        result = await session.execute(
            select(Task.due_date, Task.title).where(
                Task.archived.is_(False),
                Task.priority == "event",
                Task.due_date.is_not(None),
                Task.user_id == user_id,
            )
        )
        rows = [(row[0].date(), row[1]) for row in result.all()]

    events: dict[str, list[str]] = {}
    for d, title in rows:
        if month_start <= d <= month_end:
            events.setdefault(d.isoformat(), []).append(title)
    return events
