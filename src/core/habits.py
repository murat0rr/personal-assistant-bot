from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.habit import Habit


def _serialize(habit: Habit) -> dict:
    return {
        "id": habit.id,
        "name": habit.name,
        "streak": habit.streak,
        "last_checked": habit.last_checked,
        "target_frequency": habit.target_frequency,
    }


async def list_habits() -> list[dict]:
    """Тот же по форме список словарей, что раньше отдавал
    notion.list_habits() — build_briefing_text/build_weekly_review_text
    от смены источника не зависят."""
    async with async_session() as session:
        result = await session.execute(select(Habit))
        return [_serialize(h) for h in result.scalars().all()]


async def create_habit(name: str) -> dict:
    async with async_session() as session:
        habit = Habit(name=name)
        session.add(habit)
        await session.commit()
        await session.refresh(habit)
        return _serialize(habit)


async def get_habit(habit_id: int) -> dict:
    async with async_session() as session:
        habit = await session.get(Habit, habit_id)
        return _serialize(habit)


async def update_habit_check(habit_id: int, new_streak: int, checked_on: date) -> None:
    async with async_session() as session:
        habit = await session.get(Habit, habit_id)
        habit.streak = new_streak
        habit.last_checked = checked_on
        await session.commit()
