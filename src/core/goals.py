from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.goal import Goal


def _serialize(goal: Goal) -> dict:
    return {
        "id": goal.id,
        "sphere": goal.sphere,
        "tier": goal.tier,
        "period_start": goal.period_start.isoformat() if goal.period_start else None,
        "period_end": goal.period_end.isoformat() if goal.period_end else None,
        "text": goal.text,
    }


async def create_goal(
    sphere: str, tier: str, period_start: date | None, period_end: date | None, text: str
) -> dict:
    async with async_session() as session:
        goal = Goal(
            sphere=sphere, tier=tier, period_start=period_start, period_end=period_end, text=text
        )
        session.add(goal)
        await session.commit()
        await session.refresh(goal)
    return _serialize(goal)


async def list_goals_for_period(
    tier: str, period_start: date | None, period_end: date | None
) -> list[dict]:
    """Цели конкретного тира за конкретный период (по точному совпадению
    границ — все цели одного захода установки целей делятся ровно одним
    периодом, см. handlers/f_goals.py::start_goal_flow)."""
    async with async_session() as session:
        result = await session.execute(
            select(Goal).where(
                Goal.tier == tier,
                Goal.period_start == period_start,
                Goal.period_end == period_end,
            )
        )
        goals = result.scalars().all()
    return [_serialize(g) for g in goals]
