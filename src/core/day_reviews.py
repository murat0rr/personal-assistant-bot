from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.day_review import DayReview


async def save_review(user_id: int, review_date: date, text: str) -> None:
    """Апсерт ревью дня (Phase 48) — вызывается из
    handlers/f4_diary.py::_finish сразу после того, как текст уже
    посчитан (summarize_diary). Апсерт, а не безусловный insert: если
    вечерний опрос дневника почему-то пройден дважды за один день
    (например, повторно вручную), вторая запись должна заменить первую,
    не задублироваться (см. UniqueConstraint в models/day_review.py)."""
    async with async_session() as session:
        result = await session.execute(
            select(DayReview).where(
                DayReview.user_id == user_id, DayReview.review_date == review_date
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.text = text
        else:
            session.add(DayReview(user_id=user_id, review_date=review_date, text=text))
        await session.commit()


async def get_review(user_id: int, review_date: date) -> str | None:
    """Читает ревью дня из Postgres (Phase 48) — используется календарём
    Mini App для прошедших дней вместо повторного обращения к Claude
    (см. api.py::diary_day_endpoint)."""
    async with async_session() as session:
        result = await session.execute(
            select(DayReview.text).where(
                DayReview.user_id == user_id, DayReview.review_date == review_date
            )
        )
        return result.scalar_one_or_none()
