import time
from datetime import date, datetime

from sqlalchemy import select, update

from src.core.db import async_session
from src.models.task import Task
from src.models.task_template import TaskTemplate

_DEFAULT_PRIORITY = "средний"


def _serialize(template: TaskTemplate) -> dict:
    return {
        "id": template.id,
        "title": template.title,
        "sort_order": template.sort_order,
    }


async def list_templates(user_id: int, today: date) -> list[dict]:
    # today параметр оставлен для обратной совместимости сигнатуры (см.
    # вызов в scheduler/jobs.py) — раньше использовался для is_stale
    # (Phase 29: подсветку "давно не пользовался" убрали, сама пометка
    # last_used_date у шаблона остаётся, просто больше не красит строку).
    del today
    async with async_session() as session:
        result = await session.execute(
            select(TaskTemplate).where(
                TaskTemplate.archived.is_(False), TaskTemplate.user_id == user_id
            )
        )
        templates = result.scalars().all()
    return sorted((_serialize(t) for t in templates), key=lambda t: t["sort_order"])


async def create_template(user_id: int, title: str, source: str = "manual") -> dict:
    async with async_session() as session:
        template = TaskTemplate(user_id=user_id, title=title, source=source)
        session.add(template)
        await session.commit()
        await session.refresh(template)
    return _serialize(template)


async def create_ai_template(user_id: int, title: str) -> dict:
    """Шаблон, предложенный еженедельной джобой анализа частых задач
    (см. scheduler/jobs.py::_suggest_templates_job) — отдельная тонкая
    обёртка, чтобы вызывающий код не путался в источнике по строке."""
    return await create_template(user_id, title, source="ai")


async def _get_owned(session, template_id: int, user_id: int) -> TaskTemplate:
    """Проверка владения (Phase 40) — см. projects.py::_get_owned."""
    template = await session.get(TaskTemplate, template_id)
    if template is None or template.user_id != user_id:
        raise ValueError("template not found")
    return template


async def rename_template(template_id: int, user_id: int, title: str) -> None:
    async with async_session() as session:
        template = await _get_owned(session, template_id, user_id)
        template.title = title
        await session.commit()


async def reorder_template(template_id: int, user_id: int, sort_order: float) -> None:
    async with async_session() as session:
        template = await _get_owned(session, template_id, user_id)
        template.sort_order = sort_order
        await session.commit()


async def archive_templates_batch(user_id: int, ids: list[int]) -> None:
    if not ids:
        return
    async with async_session() as session:
        # user_id в WHERE, не только в id.in_(ids) — batch-архивация не
        # должна суметь задеть чужой шаблон, даже если id угадан/подсмотрен.
        await session.execute(
            update(TaskTemplate)
            .where(TaskTemplate.id.in_(ids), TaskTemplate.user_id == user_id)
            .values(archived=True)
        )
        await session.commit()


async def use_template(template_id: int, user_id: int, due_date: datetime) -> dict:
    """Создаёт задачу из шаблона (тот же набор дефолтных полей, что
    обычное создание через Mini App — см. api.py::create_task_endpoint)
    и обновляет last_used_date шаблона на дату НОВОЙ задачи (не сегодня —
    "на какую дату ты поставил", см. модель)."""
    async with async_session() as session:
        template = await _get_owned(session, template_id, user_id)

        task = Task(
            user_id=user_id,
            title=template.title,
            due_date=due_date,
            priority=_DEFAULT_PRIORITY,
            source="template",
            sort_order=time.time(),
        )
        session.add(task)
        template.last_used_date = due_date.date()
        await session.commit()
        await session.refresh(task)
        return {"id": task.id, "title": task.title}
