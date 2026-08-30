import calendar
from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.project import Project
from src.models.task import Task


async def sphere_breakdown() -> list[dict]:
    """Процентное соотношение задач по сферам (Phase 24) — все
    неархивированные задачи со сферой, вне зависимости от статуса
    "готово": это снимок того, как распределены намерения по сферам
    жизни прямо сейчас, а не только выполненное."""
    async with async_session() as session:
        result = await session.execute(
            select(Task.sphere).where(Task.archived.is_(False), Task.sphere.is_not(None))
        )
        spheres = [row[0] for row in result.all()]

    counts: dict[str, int] = {}
    for sphere in spheres:
        counts[sphere] = counts.get(sphere, 0) + 1
    return [{"sphere": sphere, "count": count} for sphere, count in sorted(counts.items())]


async def month_breakdown(today: date) -> dict:
    """График месяца (Phase 24) — по каждому дню текущего месяца сколько
    задач выполнено (не "стоит на этот день" — именно завершено, это
    отражает реальную продуктивность, а не план), плюс та же разбивка
    по каждому активному проекту отдельно."""
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    month_start = today.replace(day=1)
    month_end = today.replace(day=days_in_month)

    async with async_session() as session:
        result = await session.execute(
            select(Task.due_date, Task.project_id).where(
                Task.archived.is_(False),
                Task.done.is_(True),
                Task.due_date.is_not(None),
            )
        )
        rows = [(due.date(), project_id) for due, project_id in result.all()]

        project_titles: dict[int, str] = {}
        proj_result = await session.execute(select(Task.project_id).distinct())
        project_ids = {pid for (pid,) in proj_result.all() if pid is not None}
        if project_ids:
            projects = (
                await session.execute(select(Project).where(Project.id.in_(project_ids)))
            ).scalars()
            project_titles = {p.id: p.title for p in projects}

    day_labels = [f"{d:02d}" for d in range(1, days_in_month + 1)]
    all_counts = [0] * days_in_month
    per_project: dict[int, list[int]] = {}

    for due_date, project_id in rows:
        if not (month_start <= due_date <= month_end):
            continue
        idx = due_date.day - 1
        all_counts[idx] += 1
        if project_id is not None:
            per_project.setdefault(project_id, [0] * days_in_month)[idx] += 1

    projects_out = [
        {"title": project_titles.get(pid, "?"), "counts": counts, "total": sum(counts)}
        for pid, counts in per_project.items()
        if pid in project_titles
    ]
    projects_out.sort(key=lambda p: -p["total"])

    return {"days": day_labels, "all_counts": all_counts, "projects": projects_out}
