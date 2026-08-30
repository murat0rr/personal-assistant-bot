import calendar
from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.project import Project
from src.models.task import Task

_NO_PROJECT_LABEL = "Без проекта"


async def sphere_breakdown(user_id: int) -> list[dict]:
    """Процентное соотношение задач по сферам (Phase 24) — все
    неархивированные задачи со сферой, вне зависимости от статуса
    "готово": это снимок того, как распределены намерения по сферам
    жизни прямо сейчас, а не только выполненное. Плюс разбивка
    выполнено/не выполнено внутри каждой сферы (Phase 29, item 8) — для
    "расщеплённого" сегмента в тортике на фронтенде."""
    async with async_session() as session:
        result = await session.execute(
            select(Task.sphere, Task.done).where(
                Task.archived.is_(False), Task.sphere.is_not(None), Task.user_id == user_id
            )
        )
        rows = result.all()

    counts: dict[str, int] = {}
    done_counts: dict[str, int] = {}
    for sphere, done in rows:
        counts[sphere] = counts.get(sphere, 0) + 1
        if done:
            done_counts[sphere] = done_counts.get(sphere, 0) + 1
    return [
        {"sphere": sphere, "count": count, "done": done_counts.get(sphere, 0)}
        for sphere, count in sorted(counts.items())
    ]


async def month_breakdown(user_id: int, month_anchor: date) -> dict:
    """График месяца (Phase 24; листаемый по месяцам и с полным разбором
    по проектам — Phase 41) — по каждому дню месяца, на который указывает
    month_anchor (обычно 1-е число, но подходит любая дата этого месяца),
    сколько задач выполнено (не "стоит на этот день" — именно завершено,
    отражает реальную продуктивность, а не план), плюс та же разбивка по
    КАЖДОМУ активному проекту — включая те, где в этом месяце ничего не
    выполнено (нулевая строка, не пропущенная — item 1, Phase 41), плюс
    отдельная строка "Без проекта" для задач без project_id."""
    days_in_month = calendar.monthrange(month_anchor.year, month_anchor.month)[1]
    month_start = month_anchor.replace(day=1)
    month_end = month_anchor.replace(day=days_in_month)

    async with async_session() as session:
        result = await session.execute(
            select(Task.due_date, Task.project_id).where(
                Task.archived.is_(False),
                Task.done.is_(True),
                Task.due_date.is_not(None),
                Task.user_id == user_id,
            )
        )
        rows = [(due.date(), project_id) for due, project_id in result.all()]

        # Все активные проекты — не только те, где в этом месяце что-то
        # выполнено (item 1, Phase 41): проект без прогресса в этом
        # месяце должен быть виден как нулевая строка, не отсутствовать
        # молча.
        active_projects = (
            await session.execute(
                select(Project.id, Project.title).where(
                    Project.archived.is_(False), Project.user_id == user_id
                )
            )
        ).all()

    day_labels = [f"{d:02d}" for d in range(1, days_in_month + 1)]
    all_counts = [0] * days_in_month
    per_project: dict[int, list[int]] = {
        pid: [0] * days_in_month for pid, _title in active_projects
    }
    no_project_counts = [0] * days_in_month

    for due_date, project_id in rows:
        if not (month_start <= due_date <= month_end):
            continue
        idx = due_date.day - 1
        all_counts[idx] += 1
        if project_id is not None and project_id in per_project:
            per_project[project_id][idx] += 1
        elif project_id is None:
            no_project_counts[idx] += 1
        # project_id, которого нет среди active_projects (архивирован
        # после того, как задача была выполнена) — учтён в all_counts
        # (реальная продуктивность месяца), но не разложен ни в один ряд
        # по проектам: у него больше нет строки, показывать было бы
        # некуда и незачем.

    titles = dict(active_projects)
    projects_out = [
        {"title": titles[pid], "counts": counts, "total": sum(counts)}
        for pid, counts in per_project.items()
    ]
    projects_out.sort(key=lambda p: -p["total"])
    projects_out.append(
        {
            "title": _NO_PROJECT_LABEL,
            "counts": no_project_counts,
            "total": sum(no_project_counts),
        }
    )

    return {
        "year": month_anchor.year,
        "month": month_anchor.month,
        "days": day_labels,
        "all_counts": all_counts,
        "projects": projects_out,
    }
