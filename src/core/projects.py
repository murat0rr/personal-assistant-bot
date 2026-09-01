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
        "spheres": project.spheres,
        "color": project.color,
        "done": project.done,
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "end_date": project.end_date.isoformat() if project.end_date else None,
        # tier — только у бывших целей (Phase 54), None у обычных
        # проектов; core/goals.py переводит это поле в свой словарь
        # отдельно, Mini App "Проекты" его не читает.
        "tier": project.tier,
        "task_count": task_count,
        "done_count": done_count,
    }


async def _list_entities(
    user_id: int, *, tier_is_null: bool = False, tier: str | None = None
) -> list[dict]:
    """Общий листинг для обеих "личин" одной сущности (Phase 54) —
    tier_is_null=True — обычные проекты (Mini App "Проекты"),
    tier=<значение> — цели этого тира. task_count/done_count по
    project_id считаются одинаково для обеих — раньше это было
    возможно только для проектов (у целей не было настоящей связи с
    задачами), теперь есть бесплатно, как следствие слияния."""
    async with async_session() as session:
        stmt = select(Project).where(Project.archived.is_(False), Project.user_id == user_id)
        if tier_is_null:
            stmt = stmt.where(Project.tier.is_(None))
        elif tier is not None:
            stmt = stmt.where(Project.tier == tier)
        entities = (await session.execute(stmt)).scalars().all()
        counts = (
            (
                await session.execute(
                    select(
                        Task.project_id,
                        func.count(Task.id),
                        func.sum(cast(Task.done, Integer)),
                    )
                    .where(
                        Task.project_id.isnot(None),
                        Task.archived.is_(False),
                        Task.user_id == user_id,
                    )
                    .group_by(Task.project_id)
                )
            ).all()
            if entities
            else []
        )
    counts_by_id = {row[0]: (row[1], row[2] or 0) for row in counts}
    return [
        _serialize(p, *counts_by_id.get(p.id, (0, 0)))
        for p in sorted(entities, key=lambda p: (p.start_date or date.max, p.id))
    ]


async def list_projects(user_id: int) -> list[dict]:
    return await _list_entities(user_id, tier_is_null=True)


async def list_by_tier(user_id: int, tier: str) -> list[dict]:
    """Все неархивированные сущности конкретного тира — используется
    только core/goals.py (Phase 54, замена прежнего Goal-listing)."""
    return await _list_entities(user_id, tier=tier)


async def create_project(
    user_id: int,
    title: str,
    description: str | None,
    spheres: list[str],
    start_date: date | None,
    end_date: date | None,
    color: str | None = None,
    tier: str | None = None,
) -> dict:
    async with async_session() as session:
        project = Project(
            user_id=user_id,
            title=title,
            description=description,
            spheres=spheres,
            start_date=start_date,
            end_date=end_date,
            color=color,
            tier=tier,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
    return _serialize(project, 0, 0)


async def _get_owned(session, project_id: int, user_id: int) -> Project:
    """Общая проверка владения (Phase 40) — без неё чужой project_id,
    угаданный/подсмотренный, был бы доступен на правку любому
    авторизованному пользователю: session.get сам по себе не смотрит на
    user_id. Один и тот же ValueError("project not found") что для
    несуществующего id, что для чужого — снаружи не отличить "такого нет"
    от "это не ваше", как и должно быть (не спалить сам факт существования
    чужих данных)."""
    project = await session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise ValueError("project not found")
    return project


async def get_project(project_id: int, user_id: int) -> dict:
    """Одна сущность по id (Phase 54) — используется core/goals.py,
    когда нужно прочитать текущее значение поля перед пересчётом
    (например, тир при правке цели без явных новых дат). task_count/
    done_count не считает (не нужны потребителю) — 0/0 достаточно."""
    async with async_session() as session:
        project = await _get_owned(session, project_id, user_id)
        return _serialize(project, 0, 0)


async def archive_project(project_id: int, user_id: int) -> None:
    async with async_session() as session:
        project = await _get_owned(session, project_id, user_id)
        project.archived = True
        await session.commit()


async def set_project_done(project_id: int, user_id: int, done: bool) -> None:
    async with async_session() as session:
        project = await _get_owned(session, project_id, user_id)
        project.done = done
        await session.commit()


async def set_project_color(project_id: int, user_id: int, color: str | None) -> None:
    async with async_session() as session:
        project = await _get_owned(session, project_id, user_id)
        project.color = color
        await session.commit()


async def update_project(
    project_id: int,
    user_id: int,
    title: str | None = None,
    description: str | None = None,
    spheres: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    tier: str | None = None,
) -> None:
    """Правка полей проекта/цели из карточки/шторки Mini App (Phase 26,
    tier — Phase 54) — все аргументы опциональны, передаётся только то,
    что реально поменялось. spheres — список, поэтому "не трогать"
    отличается от "очистить": None значит первое, [] (пустой список —
    "без сферы") — второе. tier у обычного проекта всегда None и сюда
    не передаётся; core/goals.py сам решает, когда пересчитать
    start_date/end_date из нового тира, и передаёт их явно — здесь
    только сохраняет то, что прислали, ничего не выводит сама."""
    async with async_session() as session:
        project = await _get_owned(session, project_id, user_id)
        if title is not None:
            project.title = title
        if description is not None:
            project.description = description
        if spheres is not None:
            project.spheres = spheres
        if start_date is not None:
            project.start_date = start_date
        if end_date is not None:
            project.end_date = end_date
        if tier is not None:
            project.tier = tier
        await session.commit()


async def find_project_by_title(user_id: int, title: str) -> Project | None:
    """Нечёткое совпадение по заголовку (регистронезависимое, по
    вхождению) — используется целями (Phase 20), чтобы привязать
    сгенерированную ИИ задачу к уже существующему проекту, если Claude
    вернул подходящее название, не выдумывая точное совпадение строки."""
    async with async_session() as session:
        projects = (
            (
                await session.execute(
                    select(Project).where(Project.archived.is_(False), Project.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
    needle = title.strip().lower()
    for p in projects:
        if needle in p.title.lower() or p.title.lower() in needle:
            return p
    return None
