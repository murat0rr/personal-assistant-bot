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


def year_bounds(today: date) -> tuple[date, date]:
    return today.replace(month=1, day=1), today.replace(month=12, day=31)


# Тир -> функция границ периода — общая для Telegram-опроса по
# расписанию (scheduler/jobs.py) и ручного создания цели из Mini App
# (api.py) — период всегда считается сервером по сегодняшней дате, не
# приходит с фронтенда. Тиров всего три — quarterly/5year убраны
# целиком (Phase 27, явное решение пользователя: три тира и хватит).
GOAL_TIER_BOUNDS = {
    "weekly": week_bounds,
    "monthly": month_bounds,
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
    user_id: int,
    sphere: str,
    tier: str,
    period_start: date | None,
    period_end: date | None,
    text: str,
) -> dict:
    async with async_session() as session:
        goal = Goal(
            user_id=user_id,
            sphere=sphere,
            tier=tier,
            period_start=period_start,
            period_end=period_end,
            text=text,
        )
        session.add(goal)
        await session.commit()
        await session.refresh(goal)
    return _serialize(goal)


async def create_goal_now(
    user_id: int,
    sphere: str,
    tier: str,
    text: str,
    today: date,
    reference_date: date | None = None,
) -> dict:
    """Ручное создание цели из Mini App (Phase 26) — период считается по
    тиру и опорной дате. `reference_date` (Phase 28) — выбрана
    пользователем во всплывающем календаре ("цель на неделю через
    неделю", "любой месяц"); по умолчанию (не выбрана) — сегодняшняя
    дата, прежнее поведение."""
    bounds = GOAL_TIER_BOUNDS.get(tier)
    period_start, period_end = bounds(reference_date or today) if bounds else (None, None)
    return await create_goal(user_id, sphere, tier, period_start, period_end, text)


async def _get_owned(session, goal_id: int, user_id: int) -> Goal:
    """Проверка владения (Phase 40) — см. projects.py::_get_owned за тем
    же обоснованием."""
    goal = await session.get(Goal, goal_id)
    if goal is None or goal.user_id != user_id:
        raise ValueError("goal not found")
    return goal


async def update_goal(
    goal_id: int,
    user_id: int,
    today: date,
    text: str | None = None,
    sphere: str | None = None,
    tier: str | None = None,
    reference_date: date | None = None,
) -> None:
    """Правка полей цели из карточки Mini App (Phase 28) — как
    update_project, все аргументы опциональны, передаётся только то, что
    реально поменялось. Период — производная величина (тир + опорная
    дата), не редактируется напрямую: пересчитывается заново, если
    поменялся тир и/или опорная дата (иначе остаётся как был)."""
    async with async_session() as session:
        goal = await _get_owned(session, goal_id, user_id)
        if text is not None:
            goal.text = text
        if sphere is not None:
            goal.sphere = sphere
        new_tier = tier or goal.tier
        if tier is not None or reference_date is not None:
            bounds = GOAL_TIER_BOUNDS.get(new_tier)
            ref = reference_date or goal.period_start or today
            period_start, period_end = bounds(ref) if bounds else (None, None)
            goal.tier = new_tier
            goal.period_start = period_start
            goal.period_end = period_end
        await session.commit()


async def list_goals_for_period(
    user_id: int, tier: str, period_start: date | None, period_end: date | None
) -> list[dict]:
    """Цели конкретного тира за конкретный период (по точному совпадению
    границ — все цели одного захода установки целей делятся ровно одним
    периодом, см. handlers/f_goals.py::start_goal_flow)."""
    async with async_session() as session:
        result = await session.execute(
            select(Goal).where(
                Goal.user_id == user_id,
                Goal.tier == tier,
                Goal.period_start == period_start,
                Goal.period_end == period_end,
            )
        )
        goals = result.scalars().all()
    return [_serialize(g) for g in goals]


async def list_active_goals(user_id: int) -> list[dict]:
    """Все неархивированные цели, любых тиров/периодов — для Mini App
    (Phase 26): переключатель сам группирует по тиру на фронтенде."""
    async with async_session() as session:
        result = await session.execute(
            select(Goal).where(Goal.archived.is_(False), Goal.user_id == user_id)
        )
        goals = result.scalars().all()
    return [_serialize(g) for g in goals]


async def set_goal_done(goal_id: int, user_id: int, done: bool) -> None:
    async with async_session() as session:
        goal = await _get_owned(session, goal_id, user_id)
        goal.done = done
        await session.commit()


async def archive_goal(goal_id: int, user_id: int) -> None:
    async with async_session() as session:
        goal = await _get_owned(session, goal_id, user_id)
        goal.archived = True
        await session.commit()


async def set_goal_text(goal_id: int, user_id: int, text: str) -> None:
    async with async_session() as session:
        goal = await _get_owned(session, goal_id, user_id)
        goal.text = text
        await session.commit()
