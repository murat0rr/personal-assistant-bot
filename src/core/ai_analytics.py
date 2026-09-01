from sqlalchemy import select

from src.core import analytics as analytics_repo
from src.core import projects as projects_repo
from src.core.db import async_session
from src.core.user_location import user_today
from src.integrations.claude_client import analyze_productivity
from src.models.ai_analytics_cache import AiAnalyticsCache


async def refresh_summary(user_id: int) -> str:
    """Считает текстовую ИИ-аналитику заново и кладёт в кэш (Phase 48) —
    тот же набор источников, что раньше собирал analytics_summary_endpoint
    напрямую на каждый запрос. Используется и утренней джобой
    (scheduler/jobs.py), и самим эндпоинтом как аварийный фолбэк на
    случай, если для пользователя ещё нет ни одной строки в кэше (первый
    день после регистрации, джоба ещё не успела отработать) — общая
    функция, чтобы не дублировать эту логику в двух местах."""
    today = await user_today(user_id)
    # sphere_breakdown теперь листается по месяцам (Phase 53) и отдаёт
    # {"year", "month", "spheres"} — сводке нужен только сам список.
    spheres = (await analytics_repo.sphere_breakdown(user_id, today))["spheres"]
    month = await analytics_repo.month_breakdown(user_id, today)
    projects = await projects_repo.list_projects(user_id)
    text = await analyze_productivity(spheres, month, projects)

    async with async_session() as session:
        existing = await session.get(AiAnalyticsCache, user_id)
        if existing is not None:
            existing.text = text
        else:
            session.add(AiAnalyticsCache(user_id=user_id, text=text))
        await session.commit()
    return text


async def get_cached_summary(user_id: int) -> str | None:
    async with async_session() as session:
        result = await session.execute(
            select(AiAnalyticsCache.text).where(AiAnalyticsCache.user_id == user_id)
        )
        return result.scalar_one_or_none()
