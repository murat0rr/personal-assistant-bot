import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from src.adapters.tasker_webhook import router as tasker_webhook_router
from src.core.config import settings
from src.core.db import async_session
from src.core.notion_sync import sync_tasks_from_notion
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
    if user is None or user.get("id") != settings.telegram_user_id:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


class CreateTaskRequest(BaseModel):
    title: str


class MarkDoneRequest(BaseModel):
    done: bool


class SetDueDateRequest(BaseModel):
    due_date: str


@app.get("/miniapp/api/tasks")
async def list_tasks(_: dict = Depends(get_authorized_user)) -> dict:
    # Открытие Mini App — это и есть "триггер": подтягиваем актуальные
    # данные из Notion перед тем, как отдать список (без спама в Telegram —
    # пользователь и так смотрит на список прямо сейчас).
    await sync_tasks_from_notion(notify_on_change=False)

    async with async_session() as session:
        result = await session.execute(select(Task))
        tasks = result.scalars().all()

    return build_task_board(list(tasks))


@app.post("/miniapp/api/tasks")
async def create_task_endpoint(
    payload: CreateTaskRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    page_id, url = await notion.create_task(
        payload.title, today, _DEFAULT_PRIORITY, source="MiniApp"
    )

    async with async_session() as session:
        session.add(
            Task(
                notion_page_id=page_id,
                title=payload.title,
                due_date=today,
                priority=_DEFAULT_PRIORITY,
                status="unknown",
                source="MiniApp",
            )
        )
        await session.commit()

    return {"status": "ok", "url": url}


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


@app.get("/miniapp/api/briefing")
async def briefing(_: dict = Depends(get_authorized_user)) -> dict:
    return {"weather": await get_weather_summary()}


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
