import logging
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select, update

from src.adapters.tasker_webhook import router as tasker_webhook_router
from src.core import habits as habits_repo
from src.core import projects as projects_repo
from src.core import task_templates as templates_repo
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


@app.middleware("http")
async def _no_cache_miniapp(request: Request, call_next):
    """Telegram WebView (особенно мобильные) кэширует статику Mini App
    заметно агрессивнее обычного браузера — официальная рекомендация
    (docs.ton.org, tips-and-tricks для TMA) для index.html: полностью
    отключить кэш этими тремя заголовками, иначе после деплоя пользователь
    может продолжать видеть старую версию, пока вручную не очистит кэш
    приложения. StaticFiles по умолчанию шлёт только ETag/Last-Modified
    (условный GET), но не Cache-Control — WebView вправе не перепроверять
    вообще. Правило — на весь /miniapp: там ровно один самодостаточный
    index.html без отдельных версионируемых ассетов, экономить нечего."""
    response = await call_next(request)
    if request.url.path.startswith("/miniapp"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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


class SetSortOrderRequest(BaseModel):
    sort_order: float


class BatchArchiveRequest(BaseModel):
    ids: list[int]


class CreateProjectRequest(BaseModel):
    title: str
    description: str | None = None
    sphere: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class SetTaskProjectRequest(BaseModel):
    project_id: int | None = None


class SetTaskSphereRequest(BaseModel):
    sphere: str | None = None


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
        # Перенос на другой день — та же группа "новая/перенесённая — в
        # конец", что и при создании (Phase 13): задача уезжает в конец
        # списка того дня, куда попала, а не остаётся на случайной
        # позиции среди задач, с которыми теперь физически не соседствует.
        task.sort_order = time.time()
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
        # Смена приоритета может переместить задачу между группой событий
        # и обычных — тоже в конец новой группы, тем же правилом.
        task.sort_order = time.time()
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/reorder")
async def reorder_task(
    task_id: int, payload: SetSortOrderRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        task.sort_order = payload.sort_order
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


@app.post("/miniapp/api/tasks/{task_id}/project")
async def set_task_project(
    task_id: int, payload: SetTaskProjectRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        task.project_id = payload.project_id
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/sphere")
async def set_task_sphere(
    task_id: int, payload: SetTaskSphereRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="not found")

        task.sphere = payload.sphere
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


@app.post("/miniapp/api/tasks/archive-batch")
async def archive_tasks_batch(
    payload: BatchArchiveRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    # Режим переноса (Phase 14) — задачи помечаются "на удаление" локально
    # во фронтенде и реально архивируются одним запросом только при выходе
    # из режима (кнопка "Готово"), без похода в сеть на каждую отдельно.
    if not payload.ids:
        return {"status": "ok"}
    async with async_session() as session:
        await session.execute(update(Task).where(Task.id.in_(payload.ids)).values(archived=True))
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


# Шаблонные задачи (Phase 18) — эндпоинты зеркалят /tasks/*, но вся
# логика делегируется src/core/task_templates.py (репозиторный слой,
# как у habits, а не инлайн-SQLAlchemy, как у задач).
@app.get("/miniapp/api/templates")
async def list_templates_endpoint(_: dict = Depends(get_authorized_user)) -> list[dict]:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return await templates_repo.list_templates(today)


@app.post("/miniapp/api/templates")
async def create_template_endpoint(
    payload: SetTitleRequest, _: dict = Depends(get_authorized_user)
) -> dict:
    return await templates_repo.create_template(payload.title)


@app.post("/miniapp/api/templates/{template_id}/reorder")
async def reorder_template_endpoint(
    template_id: int, payload: SetSortOrderRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await templates_repo.reorder_template(template_id, payload.sort_order)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/templates/{template_id}/title")
async def rename_template_endpoint(
    template_id: int, payload: SetTitleRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await templates_repo.rename_template(template_id, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/templates/archive-batch")
async def archive_templates_batch_endpoint(
    payload: BatchArchiveRequest, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    await templates_repo.archive_templates_batch(payload.ids)
    return {"status": "ok"}


@app.post("/miniapp/api/templates/{template_id}/use")
async def use_template_endpoint(
    template_id: int, payload: SetDueDateRequest, _: dict = Depends(get_authorized_user)
) -> dict:
    due_date = _parse_due_date(payload.due_date)
    try:
        return await templates_repo.use_template(template_id, due_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc


# Проекты (Phase 19) — своя табличка, отношение к задачам один ко многим
# (Task.project_id). Прогресс (task_count/done_count) считается на бэкенде
# при листинге — фронтенду не нужно тянуть все задачи, чтобы нарисовать
# прогресс-бар карточки проекта.
@app.get("/miniapp/api/projects")
async def list_projects_endpoint(_: dict = Depends(get_authorized_user)) -> list[dict]:
    return await projects_repo.list_projects()


@app.post("/miniapp/api/projects")
async def create_project_endpoint(
    payload: CreateProjectRequest, _: dict = Depends(get_authorized_user)
) -> dict:
    start = date.fromisoformat(payload.start_date) if payload.start_date else None
    end = date.fromisoformat(payload.end_date) if payload.end_date else None
    return await projects_repo.create_project(
        payload.title, payload.description, payload.sphere, start, end
    )


@app.post("/miniapp/api/projects/{project_id}/archive")
async def archive_project_endpoint(
    project_id: int, _: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await projects_repo.archive_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return {"status": "ok"}


# Лёгкий staging для Mini App (SPEC.md §5) — второй, полностью отдельный от
# прод-роута static mount на том же бэкенде. index.html здесь кладётся вручную
# через scp на bind-mounted /app/staging_static (см. docker-compose.yml,
# staging_static/README.md), без пересборки образа и без отдельного стека
# контейнеров/БД — /miniapp/api/* (реальные данные, реальная авторизация) те
# же самые для обоих. check_dir=False — на случай, если bind-mount ещё не
# успел материализоваться при самом первом старте контейнера: страница просто
# 404-ит, а не роняет весь api-процесс.
_STAGING_STATIC_DIR = Path(__file__).parent.parent.parent / "staging_static"
app.mount(
    "/miniapp-staging",
    StaticFiles(directory=_STAGING_STATIC_DIR, html=True, check_dir=False),
    name="miniapp-staging",
)

# Mount регистрируем последним: Starlette матчит маршруты по порядку
# регистрации, и mount-префикс перехватил бы /miniapp/api/... раньше,
# чем до них дойдёт очередь, если объявить его выше.
_STATIC_DIR = Path(__file__).parent / "miniapp_static"
app.mount("/miniapp", StaticFiles(directory=_STATIC_DIR, html=True), name="miniapp")
