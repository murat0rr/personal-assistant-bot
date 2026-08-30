"""Затравочные данные для первой сессии нового пользователя (Phase 40) —
пробный шаблон, пробные задачи, пробный проект и пробная цель, одна
задача привязана к проекту, другая — к цели (через общую сферу, см.
models/task.py::sphere — так же, как связь "задача принадлежит цели"
устроена во всём остальном приложении, отдельного goal_id у задачи
нет). Не тестовые данные для отладки — реальные примеры того, что можно
делать в приложении, пользователь сам решает, оставить их или удалить."""

import time
from datetime import date, datetime

from src.core import goals as goals_repo
from src.core import projects as projects_repo
from src.core import task_templates as templates_repo
from src.core.db import async_session
from src.models.task import Task

_SEED_SPHERE = "развитие"


async def seed_onboarding_data(user_id: int, today: date) -> None:
    await templates_repo.create_template(user_id, "Разобрать почту")

    project = await projects_repo.create_project(
        user_id,
        title="Пробный проект",
        description="Можно переименовать, поменять сферу/цвет или удалить — это просто пример.",
        sphere=_SEED_SPHERE,
        start_date=today,
        end_date=None,
    )
    goal = await goals_repo.create_goal_now(
        user_id, _SEED_SPHERE, "weekly", "Освоить приложение", today
    )

    async with async_session() as session:
        session.add(
            Task(
                user_id=user_id,
                title="Заглянуть в «Помощь» (☰ в углу расширенного экрана)",
                due_date=datetime.combine(today, datetime.min.time()),
                priority="средний",
                source="onboarding",
                sort_order=time.time(),
                sphere=_SEED_SPHERE,
                project_id=project["id"],
            )
        )
        session.add(
            Task(
                user_id=user_id,
                title="Отметить эту задачу выполненной — тап по кружку слева",
                due_date=None,
                priority="средний",
                source="onboarding",
                sort_order=time.time() + 1,
                sphere=goal["sphere"],
            )
        )
        await session.commit()
