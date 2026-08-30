from datetime import date

from sqlalchemy import Integer, cast, func, select

from src.core.db import async_session
from src.models.project import Project
from src.models.task import Task


def _serialize(project: Project, task_count: int, done_count: int) -> dict:
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "sphere": project.sphere,
        "color": project.color,
        "done": project.done,
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "end_date": project.end_date.isoformat() if project.end_date else None,
        "task_count": task_count,
        "done_count": done_count,
    }


async def list_projects() -> list[dict]:
    async with async_session() as session:
        projects = (
            (await session.execute(select(Project).where(Project.archived.is_(False))))
            .scalars()
            .all()
        )
        counts = (
            (
                await session.execute(
                    select(
                        Task.project_id,
                        func.count(Task.id),
                        func.sum(cast(Task.done, Integer)),
                    )
                    .where(Task.project_id.isnot(None), Task.archived.is_(False))
                    .group_by(Task.project_id)
                )
            ).all()
            if projects
            else []
        )
    counts_by_id = {row[0]: (row[1], row[2] or 0) for row in counts}
    result = [
        _serialize(p, *counts_by_id.get(p.id, (0, 0)))
        for p in sorted(projects, key=lambda p: (p.start_date or date.max, p.id))
    ]
    return result


async def create_project(
    title: str,
    description: str | None,
    sphere: str | None,
    start_date: date | None,
    end_date: date | None,
    color: str | None = None,
) -> dict:
    async with async_session() as session:
        project = Project(
            title=title,
            description=description,
            sphere=sphere,
            start_date=start_date,
            end_date=end_date,
            color=color,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
    return _serialize(project, 0, 0)


async def archive_project(project_id: int) -> None:
    async with async_session() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError("project not found")
        project.archived = True
        await session.commit()


async def set_project_done(project_id: int, done: bool) -> None:
    async with async_session() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError("project not found")
        project.done = done
        await session.commit()


async def set_project_color(project_id: int, color: str | None) -> None:
    async with async_session() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError("project not found")
        project.color = color
        await session.commit()


async def update_project(
    project_id: int,
    title: str | None = None,
    description: str | None = None,
    sphere: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> None:
    """Правка полей проекта из карточки/шторки Mini App (Phase 26) — все
    аргументы опциональны, передаётся только то, что реально поменялось."""
    async with async_session() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError("project not found")
        if title is not None:
            project.title = title
        if description is not None:
            project.description = description
        if sphere is not None:
            project.sphere = sphere
        if start_date is not None:
            project.start_date = start_date
        if end_date is not None:
            project.end_date = end_date
        await session.commit()


async def find_project_by_title(title: str) -> Project | None:
    """Нечёткое совпадение по заголовку (регистронезависимое, по
    вхождению) — используется целями (Phase 20), чтобы привязать
    сгенерированную ИИ задачу к уже существующему проекту, если Claude
    вернул подходящее название, не выдумывая точное совпадение строки."""
    async with async_session() as session:
        projects = (
            (await session.execute(select(Project).where(Project.archived.is_(False))))
            .scalars()
            .all()
        )
    needle = title.strip().lower()
    for p in projects:
        if needle in p.title.lower() or p.title.lower() in needle:
            return p
    return None
