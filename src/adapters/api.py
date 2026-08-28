import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from src.core.config import settings
from src.core.db import async_session
from src.core.notion_sync import sync_tasks_from_notion
from src.core.telegram_auth import verify_miniapp_init_data
from src.integrations import notion
from src.models.task import Task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Личный ассистент API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def get_authorized_user(x_telegram_init_data: str = Header(...)) -> dict:
    user = verify_miniapp_init_data(x_telegram_init_data, settings.telegram_bot_token)
    if user is None or user.get("id") != settings.telegram_user_id:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


@app.get("/miniapp/api/tasks")
async def list_tasks(_: dict = Depends(get_authorized_user)) -> list[dict]:
    # Открытие Mini App — это и есть "триггер": подтягиваем актуальные
    # данные из Notion перед тем, как отдать список (без спама в Telegram —
    # пользователь и так смотрит на список прямо сейчас).
    await sync_tasks_from_notion(notify_on_change=False)

    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .where(func.lower(Task.status).notin_(notion.DONE_STATUS_CANDIDATES))
            .order_by(Task.due_date.asc().nulls_last())
        )
        tasks = result.scalars().all()

    return [
        {
            "notion_page_id": t.notion_page_id,
            "title": t.title,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "priority": t.priority,
            "status": t.status,
        }
        for t in tasks
    ]


@app.post("/miniapp/api/tasks/{page_id}/done")
async def mark_task_done(page_id: str, _: dict = Depends(get_authorized_user)) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, page_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        new_status = await notion.update_task_status(page_id, done=True)
        task.status = new_status
        await session.commit()

    return {"status": "ok"}


# Mount регистрируем последним: Starlette матчит маршруты по порядку
# регистрации, и mount-префикс перехватил бы /miniapp/api/... раньше,
# чем до них дойдёт очередь, если объявить его выше.
_STATIC_DIR = Path(__file__).parent / "miniapp_static"
app.mount("/miniapp", StaticFiles(directory=_STATIC_DIR, html=True), name="miniapp")
