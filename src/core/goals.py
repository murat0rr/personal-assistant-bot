from datetime import date, timedelta

from sqlalchemy import select

from src.core.db import async_session
from src.models.goal import Goal


def week_bounds(today: date) -> tuple[date, date]:
    # Цели на "предстоящую неделю" — следующий понедельник (если today
    # уже понедельник, тоже берём следующий, не текущий — формула ниже
    # даёт 7, не 0, для этого случая).
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return monday, monday + timedelta(days=6)


def month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    next_month = start.replace(day=28) + timedelta(days=4)
    end = next_month.replace(day=1) - timedelta(days=1)
    return start, end


def quarter_bounds(today: date) -> tuple[date, date]:
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    start = today.replace(month=quarter_start_month, day=1)
    end_month = quarter_start_month + 2
    next_month = start.replace(month=end_month, day=28) + timedelta(days=4)
    end = next_month.replace(day=1) - timedelta(days=1)
    return start, end


def year_bounds(today: date) -> tuple[date, date]:
    return today.replace(month=1, day=1), today.replace(month=12, day=31)


# Тир -> функция границ периода — общая для Telegram-опроса по
# расписанию (scheduler/jobs.py) и ручного создания цели из Mini App
# (api.py) — период всегда считается сервером по сегодняшней дате, не
# приходит с фронтенда. "5year" сюда не входит — у него нет периода.
GOAL_TIER_BOUNDS = {
    "weekly": week_bounds,
    "monthly": month_bounds,
    "quarterly": quarter_bounds,
    "yearly": year_bounds,
}


def _serialize(goal: Goal) -> dict:
    return {
        "id": goal.id,
        "sphere": goal.sphere,
        "tier": goal.tier,
        "period_start": goal.period_start.isoformat() if goal.period_start else None,
        "period_end": goal.period_end.isoformat() if goal.period_end else None,
        "text": goal.text,
        "done": goal.done,
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


async def create_goal_now(sphere: str, tier: str, text: str, today: date) -> dict:
    """Ручное создание цели из Mini App (Phase 26) — период считается тут
    же, по сегодняшней дате и тиру; для "5year" периода нет вообще."""
    bounds = GOAL_TIER_BOUNDS.get(tier)
    period_start, period_end = bounds(today) if bounds else (None, None)
    return await create_goal(sphere, tier, period_start, period_end, text)


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


async def list_active_goals() -> list[dict]:
    """Все неархивированные цели, любых тиров/периодов — для Mini App
    (Phase 26): переключатель сам группирует по тиру на фронтенде."""
    async with async_session() as session:
        result = await session.execute(select(Goal).where(Goal.archived.is_(False)))
        goals = result.scalars().all()
    return [_serialize(g) for g in goals]


async def set_goal_done(goal_id: int, done: bool) -> None:
    async with async_session() as session:
        goal = await session.get(Goal, goal_id)
        if goal is None:
            raise ValueError("goal not found")
        goal.done = done
        await session.commit()


async def archive_goal(goal_id: int) -> None:
    async with async_session() as session:
        goal = await session.get(Goal, goal_id)
        if goal is None:
            raise ValueError("goal not found")
        goal.archived = True
        await session.commit()


async def set_goal_text(goal_id: int, text: str) -> None:
    async with async_session() as session:
        goal = await session.get(Goal, goal_id)
        if goal is None:
            raise ValueError("goal not found")
        goal.text = text
        await session.commit()
