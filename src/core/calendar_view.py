import calendar
from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.integrations.notion import list_diary_entries
from src.models.task import Task


async def month_events(year: int, month: int) -> dict[str, list[str]]:
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
            )
        )
        rows = [(row[0].date(), row[1]) for row in result.all()]

    events: dict[str, list[str]] = {}
    for d, title in rows:
        if month_start <= d <= month_end:
            events.setdefault(d.isoformat(), []).append(title)
    return events


async def month_diary_moods(year: int, month: int) -> dict[str, float]:
    """Для плиток месячного календаря (Phase 27) — компактный индикатор
    "как прошёл день" по прошедшим датам: средний балл вечерней рефлексии
    (physical/social/productivity/happiness, шкала 1-3, см.
    handlers/f4_diary.py) за те дни месяца, где рефлексия реально
    заполнена. Дни без записи или с пустыми оценками просто отсутствуют в
    ответе — фронтенд ничего не рисует поверх такой плитки."""
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    entries = await list_diary_entries()
    moods: dict[str, float] = {}
    for entry in entries:
        entry_date = entry.get("entry_date")
        if entry_date is None or not (month_start <= entry_date <= month_end):
            continue
        ratings = [
            entry.get(field) for field in ("physical", "social", "productivity", "happiness")
        ]
        filled = [r for r in ratings if r is not None]
        if not filled:
            continue
        moods[entry_date.isoformat()] = sum(filled) / len(filled)
    return moods
