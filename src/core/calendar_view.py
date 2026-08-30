import calendar
from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.task import Task


async def month_events(year: int, month: int) -> dict[str, bool]:
    """Для месячного календаря в Mini App (Phase 26) — только задачи-
    события (priority="event"), не все задачи: требование явно про
    события, не про общую загрузку дня (для неё есть график месяца в
    аналитике)."""
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    async with async_session() as session:
        result = await session.execute(
            select(Task.due_date).where(
                Task.archived.is_(False),
                Task.priority == "event",
                Task.due_date.is_not(None),
            )
        )
        due_dates = [row[0].date() for row in result.all()]

    has_event = {d for d in due_dates if month_start <= d <= month_end}
    return {d.isoformat(): True for d in has_event}
