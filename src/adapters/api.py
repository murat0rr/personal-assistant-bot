import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from src.adapters.tasker_webhook import router as tasker_webhook_router
from src.core import habits as habits_repo
from src.core.auth import is_authorized
from src.core.config import settings
from src.core.db import async_session
from src.core.telegram_auth import verify_miniapp_init_data
from src.handlers.f8_habits import check_habit
from src.handlers.miniapp_tasks import build_task_board
from src.integrations.weather import get_weather_summary
from src.models.task import Task

_DEFAULT_PRIORITY = "средний"


def _parse_due_date(value: str) -> datetime:
    """due_date в БД — timestamp. Фронтенд шлёт либо чистую дату
    ("2026-09-01", обычная задача — идёт на полночь), либо
    datetime-local ("2026-09-01T14:30", событие со временем начала)."""
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.combine(date.fromisoformat(value), datetime.min.time())


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Личный ассистент API")
app.include_router(tasker_webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def get_authorized_user(x_telegram_init_data: str = Header(...)) -> dict:
    user = verify_miniapp_init_data(x_telegram_init_data, settings.telegram_bot_token)
    user_id = user.get("id") if user else None
    if user_id is None or not await is_authorized(user_id):
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


class CreateTaskRequest(BaseModel):
    title: str
    due_date: str | None = None


class MarkDoneRequest(BaseModel):
    done: bool


class SetDueDateRequest(BaseModel):
    due_date: str


class SetPriorityRequest(BaseModel):
    priority: str


class SetTitleRequest(BaseModel):
    title: str


@app.get("/miniapp/api/tasks")
async def list_tasks(_: dict = Depends(get_authorized_user)) -> dict:
    # Postgres — единственный источник правды для задач (Phase 10), поэтому
    # это простое чтение без похода куда-либо ещё.
    async with async_session() as session:
        result = await session.execute(select(Task).where(Task.archived.is_(False)))
        tasks = result.scalars().all()

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return build_task_board(list(tasks), today)


@app.post("/miniapp/api/tasks")
async def create_task_endpoint(
    payload: CreateTaskRequest, _: dict = Depends(get_authorized_user)
) -> dict:
    # due_date=None — валидный случай (задача из Инбокса, без даты), не
    # заменяем его на "сегодня": фронтенд всегда передаёт то, что реально
    # имел в виду (конкретный день/дата+время, либо явно null).
    due_date = _parse_due_date(payload.due_date) if payload.due_date else None

    async with async_session() as session:
        task = Task(
            title=payload.title,
            due_date=due_date,
            priority=_DEFAULT_PRIORITY,
            source="MiniApp",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

    return {"status": "ok", "id": task.id}


@app.post("/miniapp/api/tasks/{task_id}/done")
async def mark_task_done(
    task_id: int, payload: MarkDoneRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        task.done = payload.done
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/due-date")
async def set_task_due_date(
    task_id: int, payload: SetDueDateRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        task.due_date = _parse_due_date(payload.due_date)
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/priority")
async def set_task_priority(
    task_id: int, payload: SetPriorityRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        task.priority = payload.priority
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/title")
async def set_task_title(
    task_id: int, payload: SetTitleRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="empty title")

    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        task.title = title
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/archive")
async def archive_task_endpoint(
    task_id: int, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        task.archived = True
        await session.commit()

    return {"status": "ok"}


@app.get("/miniapp/api/briefing")
async def briefing(_: dict = Depends(get_authorized_user)) -> dict:
    return {"weather": await get_weather_summary()}


class CreateHabitRequest(BaseModel):
    name: str


@app.get("/miniapp/api/habits")
async def list_habits_endpoint(_: dict = Depends(get_authorized_user)) -> list[dict]:
    return await habits_repo.list_habits()


@app.post("/miniapp/api/habits")
async def create_habit_endpoint(
    payload: CreateHabitRequest, _: dict = Depends(get_authorized_user)
) -> dict:
    habit = await habits_repo.create_habit(payload.name)
    return {"status": "ok", "id": habit["id"]}


@app.post("/miniapp/api/habits/{habit_id}/check")
async def mark_habit_checked(habit_id: int, _: dict = Depends(get_authorized_user)) -> dict:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    new_streak = await check_habit(habit_id, today)
    return {"status": "ok", "streak": new_streak}


# Mount регистрируем последним: Starlette матчит маршруты по порядку
# регистрации, и mount-префикс перехватил бы /miniapp/api/... раньше,
# чем до них дойдёт очередь, если объявить его выше.
_STATIC_DIR = Path(__file__).parent / "miniapp_static"
app.mount("/miniapp", StaticFiles(directory=_STATIC_DIR, html=True), name="miniapp")
