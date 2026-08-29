import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from src.adapters.tasker_webhook import router as tasker_webhook_router
from src.core.auth import is_authorized
from src.core.config import settings
from src.core.db import async_session
from src.core.telegram_auth import verify_miniapp_init_data
from src.handlers.f8_habits import check_habit
from src.handlers.miniapp_tasks import build_task_board
from src.integrations import notion
from src.integrations.weather import get_weather_summary
from src.models.task import Task

_DEFAULT_PRIORITY = "средний"

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


@app.get("/miniapp/api/tasks")
async def list_tasks(_: dict = Depends(get_authorized_user)) -> dict:
    # Никакого похода в Notion здесь — только чтение локального кэша,
    # чтобы открытие Mini App было мгновенным. Кэш держит свежим плановая
    # джоба раз в 10 минут (src/scheduler/jobs.py::_sync_tasks_job) плюс
    # мутации из самого Mini App пишут в кэш сразу же.
    async with async_session() as session:
        result = await session.execute(select(Task))
        tasks = result.scalars().all()

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return build_task_board(list(tasks), today)


@app.post("/miniapp/api/tasks")
async def create_task_endpoint(
    payload: CreateTaskRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    # due_date=None — валидный случай (задача из Инбокса, без даты), не
    # заменяем его на "сегодня": фронтенд теперь всегда передаёт то, что
    # реально имел в виду (конкретный день, либо явно null).
    due_date = date.fromisoformat(payload.due_date) if payload.due_date else None
    page_id, url = await notion.create_task(
        payload.title, due_date, _DEFAULT_PRIORITY, source="MiniApp"
    )

    async with async_session() as session:
        session.add(
            Task(
                notion_page_id=page_id,
                title=payload.title,
                due_date=due_date,
                priority=_DEFAULT_PRIORITY,
                status="unknown",
                source="MiniApp",
            )
        )
        await session.commit()

    return {"status": "ok", "url": url, "page_id": page_id}


@app.post("/miniapp/api/tasks/{page_id}/done")
async def mark_task_done(
    page_id: str, payload: MarkDoneRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, page_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        new_status = await notion.update_task_status(page_id, done=payload.done)
        task.status = new_status
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{page_id}/due-date")
async def set_task_due_date(
    page_id: str, payload: SetDueDateRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, page_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        due_date = date.fromisoformat(payload.due_date)
        await notion.update_task_due_date(page_id, due_date)
        task.due_date = due_date
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{page_id}/archive")
async def archive_task_endpoint(
    page_id: str, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await notion.archive_task(page_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    async with async_session() as session:
        task = await session.get(Task, page_id)
        if task is not None:
            await session.delete(task)
            await session.commit()

    return {"status": "ok"}


@app.get("/miniapp/api/briefing")
async def briefing(_: dict = Depends(get_authorized_user)) -> dict:
    return {"weather": await get_weather_summary()}


class CreateHabitRequest(BaseModel):
    name: str


@app.get("/miniapp/api/habits")
async def list_habits_endpoint(_: dict = Depends(get_authorized_user)) -> list[dict]:
    if not settings.notion_habits_db_id:
        return []
    habits = await notion.list_habits()
    return [
        {
            "notion_page_id": h["notion_page_id"],
            "name": h["name"],
            "streak": h["streak"],
        }
        for h in habits
    ]


@app.post("/miniapp/api/habits")
async def create_habit_endpoint(
    payload: CreateHabitRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    if not settings.notion_habits_db_id:
        raise HTTPException(status_code=400, detail="Notion Habits не настроен")
    _page_id, url = await notion.create_habit(payload.name)
    return {"status": "ok", "url": url}


@app.post("/miniapp/api/habits/{page_id}/check")
async def mark_habit_checked(page_id: str, _: dict = Depends(get_authorized_user)) -> dict:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    new_streak = await check_habit(page_id, today)
    return {"status": "ok", "streak": new_streak}


# Mount регистрируем последним: Starlette матчит маршруты по порядку
# регистрации, и mount-префикс перехватил бы /miniapp/api/... раньше,
# чем до них дойдёт очередь, если объявить его выше.
_STATIC_DIR = Path(__file__).parent / "miniapp_static"
app.mount("/miniapp", StaticFiles(directory=_STATIC_DIR, html=True), name="miniapp")
