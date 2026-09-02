import calendar
from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.day_review import DayReview

_RATING_FIELDS = ("physical", "social", "productivity", "happiness")


def _serialize(row: DayReview) -> dict:
    return {
        "entry_date": row.review_date,
        "physical": row.physical,
        "social": row.social,
        "productivity": row.productivity,
        "happiness": row.happiness,
        "highlight": row.highlight,
        "reflection": row.reflection,
        "summary": row.text,
    }


async def save_diary_entry(
    user_id: int,
    entry_date: date,
    ratings: dict[str, int | None],
    highlight: str | None,
    reflection: str | None,
    summary: str | None,
) -> None:
    """Полный апсерт записи дневника (Phase 48 — раньше только текстовый
    саммари; Phase 62 — единственный источник правды целиком, раньше
    оценки/highlight/reflection жили только в Notion). Апсерт, а не
    безусловный insert: если вечерний опрос дневника почему-то пройден
    дважды за один день (например, повторно вручную), вторая запись
    должна заменить первую, не задублироваться (см. UniqueConstraint в
    models/day_review.py). Вызывается из handlers/f4_diary.py::_finish."""
    async with async_session() as session:
        result = await session.execute(
            select(DayReview).where(
                DayReview.user_id == user_id, DayReview.review_date == entry_date
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = DayReview(user_id=user_id, review_date=entry_date)
            session.add(existing)
        for field in _RATING_FIELDS:
            setattr(existing, field, ratings.get(field))
        existing.highlight = highlight
        existing.reflection = reflection
        existing.text = summary
        await session.commit()


async def get_diary_entry(user_id: int, entry_date: date) -> dict | None:
    """Читает запись дневника целиком (Phase 62 — раньше оценки/
    highlight читались из Notion отдельным заходом, здесь читается
    вместе с саммари одним запросом). Используется календарём Mini App
    (см. api.py::diary_day_endpoint)."""
    async with async_session() as session:
        result = await session.execute(
            select(DayReview).where(
                DayReview.user_id == user_id, DayReview.review_date == entry_date
            )
        )
        row = result.scalar_one_or_none()
        return _serialize(row) if row is not None else None


async def entries_since(user_id: int, start_date: date) -> list[dict]:
    """Записи дневника от start_date по сегодня включительно (Phase 62)
    — используется недельным ревью (handlers/f11_weekly_review.py),
    раньше получавшим ВЕСЬ датасет Notion разом и фильтровавшим на
    своей стороне; здесь фильтр уже на уровне SQL."""
    async with async_session() as session:
        result = await session.execute(
            select(DayReview).where(
                DayReview.user_id == user_id, DayReview.review_date >= start_date
            )
        )
        return [_serialize(row) for row in result.scalars().all()]


async def month_diary_moods(user_id: int, year: int, month: int) -> dict[str, float]:
    """Для плиток месячного календаря (Phase 27, переехало с Notion на
    Postgres в Phase 62) — компактный индикатор "как прошёл день" по
    прошедшим датам: средний балл вечерней рефлексии
    (physical/social/productivity/happiness, шкала 1-3) за те дни
    месяца, где рефлексия реально заполнена. Дни без записи или с
    пустыми оценками просто отсутствуют в ответе — фронтенд ничего не
    рисует поверх такой плитки. В отличие от старой Notion-версии,
    честно фильтруется по user_id на уровне SQL (Notion был один
    воркспейс на всех, эта фильтрация физически была невозможна)."""
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    async with async_session() as session:
        result = await session.execute(
            select(DayReview).where(
                DayReview.user_id == user_id,
                DayReview.review_date >= month_start,
                DayReview.review_date <= month_end,
            )
        )
        rows = result.scalars().all()

    moods: dict[str, float] = {}
    for row in rows:
        filled = [
            getattr(row, field) for field in _RATING_FIELDS if getattr(row, field) is not None
        ]
        if not filled:
            continue
        moods[row.review_date.isoformat()] = sum(filled) / len(filled)
    return moods
