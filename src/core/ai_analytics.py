from datetime import date

from sqlalchemy import select

from src.core import analytics as analytics_repo
from src.core import projects as projects_repo
from src.core.db import async_session
from src.integrations.claude_client import analyze_productivity
from src.models.ai_analytics_cache import AiAnalyticsCache


async def refresh_summary(user_id: int, month_anchor: date) -> str:
    """Считает текстовую ИИ-аналитику заново для месяца month_anchor и
    кладёт в кэш (Phase 48, помесячно — Phase 89) — тот же набор
    источников, что раньше собирал analytics_summary_endpoint напрямую
    на каждый запрос. Используется и утренней джобой (scheduler/jobs.py,
    всегда для текущего месяца), и самим эндпоинтом как аварийный
    фолбэк — но только для ТЕКУЩЕГО месяца (см. api.py), не для
    произвольного исторического, чтобы свайп по месяцам не бил пачкой
    запросов к Claude."""
    # sphere_breakdown теперь листается по месяцам (Phase 53) и отдаёт
    # {"year", "month", "spheres"} — сводке нужен только сам список.
    spheres = (await analytics_repo.sphere_breakdown(user_id, month_anchor))["spheres"]
    month = await analytics_repo.month_breakdown(user_id, month_anchor)
    projects = await projects_repo.list_projects(user_id)
    text = await analyze_productivity(spheres, month, projects)

    async with async_session() as session:
        existing = await session.get(
            AiAnalyticsCache, (user_id, month_anchor.year, month_anchor.month)
        )
        if existing is not None:
            existing.text = text
        else:
            session.add(
                AiAnalyticsCache(
                    user_id=user_id, year=month_anchor.year, month=month_anchor.month, text=text
                )
            )
        await session.commit()
    return text


async def get_cached_summary(user_id: int, month_anchor: date) -> str | None:
    async with async_session() as session:
        result = await session.execute(
            select(AiAnalyticsCache.text).where(
                AiAnalyticsCache.user_id == user_id,
                AiAnalyticsCache.year == month_anchor.year,
                AiAnalyticsCache.month == month_anchor.month,
            )
        )
        return result.scalar_one_or_none()
