import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import AfterValidator, BaseModel
from sqlalchemy import select, update

from src.adapters.tasker_webhook import router as tasker_webhook_router
from src.core import analytics as analytics_repo
from src.core import calendar_view
from src.core import goals as goals_repo
from src.core import habits as habits_repo
from src.core import projects as projects_repo
from src.core import task_templates as templates_repo
from src.core.auth import is_authorized
from src.core.config import settings
from src.core.db import async_session
from src.core.telegram_auth import verify_miniapp_init_data
from src.core.user_location import apply_stored_timezone
from src.handlers.f8_habits import check_habit
from src.handlers.miniapp_tasks import build_task_board
from src.integrations.claude_client import analyze_productivity, find_tasks_for_entity
from src.integrations.notion import list_diary_entries
from src.integrations.weather import get_weather_summary
from src.models.task import Task

_DEFAULT_PRIORITY = "средний"

# Тот же закрытый список, что и SPHERES на фронтенде (index.html) — там
# это просто набор кнопок выбора, но само API до ревизии безопасности
# (Phase 39) принимало в поле sphere любую строку без проверки: обычный
# фронтенд никогда не отправит ничего другого, но прямой запрос к API
# (с валидной подписью initData) мог бы записать произвольный текст,
# который потом рендерился в аналитике без экранирования (см. Phase 39,
# escapeHtml в index.html — сам XSS уже закрыт на выводе, эта проверка
# на входе — дополнительный слой, не даёт мусору попасть в БД вообще).
_SPHERES = {"учёба", "работа", "спорт", "развитие", "отношения"}


def _validate_sphere(value: str | None) -> str | None:
    if value is not None and value not in _SPHERES:
        raise ValueError(f"недопустимая сфера: {value!r}")
    return value


SphereField = Annotated[str | None, AfterValidator(_validate_sphere)]
# Пидантик проверяет базовый тип (str, без None) раньше AfterValidator,
# так что в _validate_sphere value тут гарантированно не None — можно
# переиспользовать ту же функцию для обязательного варианта поля.
RequiredSphereField = Annotated[str, AfterValidator(_validate_sphere)]


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


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Отдельный процесс от bot — своя память, свой settings.timezone.
    # Подтягиваем то, что владелец мог установить командой /timezone,
    # сразу на старте (Phase 39, см. src/core/user_location.py). Без
    # этого API-процесс продолжал бы считать "сегодня" по старой зоне
    # (месячный календарь и т.д.; автоочистка чата тут не участвует — она
    # только в bot) до следующего деплоя.
    await apply_stored_timezone()
    yield


app = FastAPI(title="Личный ассистент API", lifespan=_lifespan)
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
    sphere: SphereField = None
    start_date: str | None = None
    end_date: str | None = None
    color: str | None = None
    analyze: bool = False


class SetTaskProjectRequest(BaseModel):
    project_id: int | None = None


class SetTaskSphereRequest(BaseModel):
    sphere: SphereField = None


class SetDoneRequest(BaseModel):
    done: bool


class SetColorRequest(BaseModel):
    color: str | None = None


class EditProjectRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    sphere: SphereField = None
    start_date: str | None = None
    end_date: str | None = None


class CreateGoalRequest(BaseModel):
    sphere: RequiredSphereField
    tier: str
    text: str
    analyze: bool = False
    reference_date: str | None = None


class SetGoalTextRequest(BaseModel):
    text: str


class EditGoalRequest(BaseModel):
    text: str | None = None
    sphere: SphereField = None
    tier: str | None = None
    reference_date: str | None = None


async def _get_owned_task(session, task_id: int, uid: int) -> Task:
    """Проверка владения (Phase 40) — тот же принцип, что
    core/projects.py::_get_owned, но задачи (в отличие от проектов/
    целей/шаблонов) правятся напрямую в api.py, не через репозиторный
    слой, так что helper здесь, а не в src/core/*."""
    task = await session.get(Task, task_id)
    if task is None or task.user_id != uid:
        raise HTTPException(status_code=404, detail="not found")
    return task


@app.get("/miniapp/api/tasks")
async def list_tasks(user: dict = Depends(get_authorized_user)) -> dict:
    uid = user["id"]
    # Postgres — единственный источник правды для задач (Phase 10), поэтому
    # это простое чтение без похода куда-либо ещё.
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.archived.is_(False), Task.user_id == uid)
        )
        tasks = result.scalars().all()

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return build_task_board(list(tasks), today)


@app.post("/miniapp/api/tasks")
async def create_task_endpoint(
    payload: CreateTaskRequest, user: dict = Depends(get_authorized_user)
) -> dict:
    # due_date=None — валидный случай (задача из Инбокса, без даты), не
    # заменяем его на "сегодня": фронтенд всегда передаёт то, что реально
    # имел в виду (конкретный день/дата+время, либо явно null).
    due_date = _parse_due_date(payload.due_date) if payload.due_date else None

    async with async_session() as session:
        task = Task(
            user_id=user["id"],
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
    task_id: int, payload: MarkDoneRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await _get_owned_task(session, task_id, user["id"])
        task.done = payload.done
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/due-date")
async def set_task_due_date(
    task_id: int, payload: SetDueDateRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await _get_owned_task(session, task_id, user["id"])
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
    task_id: int, payload: SetPriorityRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await _get_owned_task(session, task_id, user["id"])
        task.priority = payload.priority
        # Смена приоритета может переместить задачу между группой событий
        # и обычных — тоже в конец новой группы, тем же правилом.
        task.sort_order = time.time()
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/reorder")
async def reorder_task(
    task_id: int, payload: SetSortOrderRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await _get_owned_task(session, task_id, user["id"])
        task.sort_order = payload.sort_order
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/title")
async def set_task_title(
    task_id: int, payload: SetTitleRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="empty title")

    async with async_session() as session:
        task = await _get_owned_task(session, task_id, user["id"])
        task.title = title
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/project")
async def set_task_project(
    task_id: int, payload: SetTaskProjectRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await _get_owned_task(session, task_id, user["id"])
        task.project_id = payload.project_id
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/sphere")
async def set_task_sphere(
    task_id: int, payload: SetTaskSphereRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await _get_owned_task(session, task_id, user["id"])
        task.sphere = payload.sphere
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/{task_id}/archive")
async def archive_task_endpoint(
    task_id: int, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    async with async_session() as session:
        task = await _get_owned_task(session, task_id, user["id"])
        task.archived = True
        await session.commit()

    return {"status": "ok"}


@app.post("/miniapp/api/tasks/archive-batch")
async def archive_tasks_batch(
    payload: BatchArchiveRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    # Режим переноса (Phase 14) — задачи помечаются "на удаление" локально
    # во фронтенде и реально архивируются одним запросом только при выходе
    # из режима (кнопка "Готово"), без похода в сеть на каждую отдельно.
    if not payload.ids:
        return {"status": "ok"}
    async with async_session() as session:
        # user_id в WHERE — тот же принцип, что task_templates_repo
        # ::archive_templates_batch: batch-операция не должна суметь
        # задеть чужую задачу, даже если id угадан/подсмотрен.
        await session.execute(
            update(Task)
            .where(Task.id.in_(payload.ids), Task.user_id == user["id"])
            .values(archived=True)
        )
        await session.commit()

    return {"status": "ok"}


@app.get("/miniapp/api/briefing")
async def briefing(user: dict = Depends(get_authorized_user)) -> dict:
    return {"weather": await get_weather_summary(user["id"])}


class CreateHabitRequest(BaseModel):
    name: str


@app.get("/miniapp/api/habits")
async def list_habits_endpoint(user: dict = Depends(get_authorized_user)) -> list[dict]:
    return await habits_repo.list_habits(user["id"])


@app.post("/miniapp/api/habits")
async def create_habit_endpoint(
    payload: CreateHabitRequest, user: dict = Depends(get_authorized_user)
) -> dict:
    habit = await habits_repo.create_habit(user["id"], payload.name)
    return {"status": "ok", "id": habit["id"]}


@app.post("/miniapp/api/habits/{habit_id}/check")
async def mark_habit_checked(habit_id: int, user: dict = Depends(get_authorized_user)) -> dict:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    try:
        new_streak = await check_habit(habit_id, user["id"], today)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="habit not found") from exc
    return {"status": "ok", "streak": new_streak}


# Шаблонные задачи (Phase 18) — эндпоинты зеркалят /tasks/*, но вся
# логика делегируется src/core/task_templates.py (репозиторный слой,
# как у habits, а не инлайн-SQLAlchemy, как у задач).
@app.get("/miniapp/api/templates")
async def list_templates_endpoint(user: dict = Depends(get_authorized_user)) -> list[dict]:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return await templates_repo.list_templates(user["id"], today)


@app.post("/miniapp/api/templates")
async def create_template_endpoint(
    payload: SetTitleRequest, user: dict = Depends(get_authorized_user)
) -> dict:
    return await templates_repo.create_template(user["id"], payload.title)


@app.post("/miniapp/api/templates/{template_id}/reorder")
async def reorder_template_endpoint(
    template_id: int, payload: SetSortOrderRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await templates_repo.reorder_template(template_id, user["id"], payload.sort_order)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/templates/{template_id}/title")
async def rename_template_endpoint(
    template_id: int, payload: SetTitleRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await templates_repo.rename_template(template_id, user["id"], payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/templates/archive-batch")
async def archive_templates_batch_endpoint(
    payload: BatchArchiveRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    await templates_repo.archive_templates_batch(user["id"], payload.ids)
    return {"status": "ok"}


@app.post("/miniapp/api/templates/{template_id}/use")
async def use_template_endpoint(
    template_id: int, payload: SetDueDateRequest, user: dict = Depends(get_authorized_user)
) -> dict:
    due_date = _parse_due_date(payload.due_date)
    try:
        return await templates_repo.use_template(template_id, user["id"], due_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc


# Проекты (Phase 19) — своя табличка, отношение к задачам один ко многим
# (Task.project_id). Прогресс (task_count/done_count) считается на бэкенде
# при листинге — фронтенду не нужно тянуть все задачи, чтобы нарисовать
# прогресс-бар карточки проекта.
@app.get("/miniapp/api/projects")
async def list_projects_endpoint(user: dict = Depends(get_authorized_user)) -> list[dict]:
    return await projects_repo.list_projects(user["id"])


@app.post("/miniapp/api/projects")
async def create_project_endpoint(
    payload: CreateProjectRequest, user: dict = Depends(get_authorized_user)
) -> dict:
    uid = user["id"]
    start = date.fromisoformat(payload.start_date) if payload.start_date else None
    end = date.fromisoformat(payload.end_date) if payload.end_date else None
    project = await projects_repo.create_project(
        uid, payload.title, payload.description, payload.sphere, start, end, payload.color
    )
    if payload.analyze:
        await _analyze_and_link_project(
            uid, project["id"], project["title"], project["description"]
        )
    return project


@app.post("/miniapp/api/projects/{project_id}/archive")
async def archive_project_endpoint(
    project_id: int, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await projects_repo.archive_project(project_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/projects/{project_id}/done")
async def set_project_done_endpoint(
    project_id: int, payload: SetDoneRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await projects_repo.set_project_done(project_id, user["id"], payload.done)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/projects/{project_id}/color")
async def set_project_color_endpoint(
    project_id: int, payload: SetColorRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await projects_repo.set_project_color(project_id, user["id"], payload.color)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/projects/{project_id}/edit")
async def edit_project_endpoint(
    project_id: int, payload: EditProjectRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    start = date.fromisoformat(payload.start_date) if payload.start_date else None
    end = date.fromisoformat(payload.end_date) if payload.end_date else None
    try:
        await projects_repo.update_project(
            project_id,
            user["id"],
            title=payload.title,
            description=payload.description,
            sphere=payload.sphere,
            start_date=start,
            end_date=end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return {"status": "ok"}


async def _unlinked_candidate_tasks(user_id: int, field: str) -> list[dict]:
    """Задачи без привязки (field — "project_id" или "sphere") из
    инбокса и всех будущих дат — кандидаты для "проанализировать и
    добавить" (Phase 26). Прошлые/просроченные не трогаем — это уже
    история, а не то, что имеет смысл молча перекладывать в проект/цель."""
    # due_date в БД — naive timestamp (см. models/task.py) — сравнение
    # тоже должно быть naive, иначе asyncpg ругается на offset-aware
    # datetime (тот же приём, что в scheduler/jobs.py::_suggest_templates_job).
    today_start = datetime.combine(
        datetime.now(ZoneInfo(settings.timezone)).date(), datetime.min.time()
    )
    column = Task.project_id if field == "project_id" else Task.sphere
    async with async_session() as session:
        result = await session.execute(
            select(Task.id, Task.title).where(
                Task.archived.is_(False),
                Task.done.is_(False),
                column.is_(None),
                (Task.due_date.is_(None) | (Task.due_date >= today_start)),
                Task.user_id == user_id,
            )
        )
        return [{"id": row[0], "title": row[1]} for row in result.all()]


async def _analyze_and_link_project(
    user_id: int, project_id: int, title: str, description: str | None
) -> int:
    candidates = await _unlinked_candidate_tasks(user_id, "project_id")
    matched_ids = await find_tasks_for_entity(title, description, candidates)
    if not matched_ids:
        return 0
    async with async_session() as session:
        await session.execute(
            update(Task)
            .where(Task.id.in_(matched_ids), Task.user_id == user_id)
            .values(project_id=project_id)
        )
        await session.commit()
    return len(matched_ids)


@app.post("/miniapp/api/projects/{project_id}/analyze")
async def analyze_project_endpoint(
    project_id: int, user: dict = Depends(get_authorized_user)
) -> dict:
    uid = user["id"]
    projects = await projects_repo.list_projects(uid)
    project = next((p for p in projects if p["id"] == project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    linked = await _analyze_and_link_project(
        uid, project_id, project["title"], project["description"]
    )
    return {"linked": linked}


# Цели (Phase 20 — бэкенд/Telegram; Phase 26 — Mini App). Период
# считается сервером по тиру и сегодняшней дате (см. core/goals.py::
# create_goal_now) — фронтенд его не присылает.
@app.get("/miniapp/api/goals")
async def list_goals_endpoint(user: dict = Depends(get_authorized_user)) -> list[dict]:
    return await goals_repo.list_active_goals(user["id"])


@app.post("/miniapp/api/goals")
async def create_goal_endpoint(
    payload: CreateGoalRequest, user: dict = Depends(get_authorized_user)
) -> dict:
    uid = user["id"]
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    reference_date = date.fromisoformat(payload.reference_date) if payload.reference_date else None
    goal = await goals_repo.create_goal_now(
        uid, payload.sphere, payload.tier, payload.text, today, reference_date
    )
    if payload.analyze:
        candidates = await _unlinked_candidate_tasks(uid, "sphere")
        matched_ids = await find_tasks_for_entity(goal["text"], None, candidates)
        if matched_ids:
            async with async_session() as session:
                await session.execute(
                    update(Task)
                    .where(Task.id.in_(matched_ids), Task.user_id == uid)
                    .values(sphere=payload.sphere)
                )
                await session.commit()
    return goal


@app.post("/miniapp/api/goals/{goal_id}/done")
async def set_goal_done_endpoint(
    goal_id: int, payload: SetDoneRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await goals_repo.set_goal_done(goal_id, user["id"], payload.done)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="goal not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/goals/{goal_id}/archive")
async def archive_goal_endpoint(
    goal_id: int, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await goals_repo.archive_goal(goal_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="goal not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/goals/{goal_id}/text")
async def set_goal_text_endpoint(
    goal_id: int, payload: SetGoalTextRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    try:
        await goals_repo.set_goal_text(goal_id, user["id"], payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="goal not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/goals/{goal_id}/edit")
async def edit_goal_endpoint(
    goal_id: int, payload: EditGoalRequest, user: dict = Depends(get_authorized_user)
) -> dict[str, str]:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    reference_date = date.fromisoformat(payload.reference_date) if payload.reference_date else None
    try:
        await goals_repo.update_goal(
            goal_id,
            user["id"],
            today,
            text=payload.text,
            sphere=payload.sphere,
            tier=payload.tier,
            reference_date=reference_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="goal not found") from exc
    return {"status": "ok"}


@app.post("/miniapp/api/goals/{goal_id}/analyze")
async def analyze_goal_endpoint(goal_id: int, user: dict = Depends(get_authorized_user)) -> dict:
    uid = user["id"]
    goals = await goals_repo.list_active_goals(uid)
    goal = next((g for g in goals if g["id"] == goal_id), None)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    candidates = await _unlinked_candidate_tasks(uid, "sphere")
    matched_ids = await find_tasks_for_entity(goal["text"], None, candidates)
    if matched_ids:
        async with async_session() as session:
            await session.execute(
                update(Task)
                .where(Task.id.in_(matched_ids), Task.user_id == uid)
                .values(sphere=goal["sphere"])
            )
            await session.commit()
    return {"linked": len(matched_ids)}


def _is_owner(user_id: int) -> bool:
    return user_id == settings.telegram_user_id


# Дневник и заметки — пока только у основного владельца (Phase 40,
# явное решение при обсуждении многопользовательской авторизации):
# и то, и другое живёт в Notion, привязанном к одному конкретному
# воркспейсу/токену, не к отдельному Telegram-пользователю. Остальным
# авторизованным — не тихая пустота и не ошибка, а понятный ответ, что
# функция ещё не готова для них конкретно (см. _NOT_READY_FOR_OTHERS).
_NOT_READY_FOR_OTHERS = "Дневник и заметки пока доступны только основному пользователю."


# Месячный календарь (Phase 26) — только события (priority="event"), не
# вся загрузка дня (для этого есть график месяца в аналитике).
@app.get("/miniapp/api/calendar/month")
async def calendar_month_endpoint(
    month: str, user: dict = Depends(get_authorized_user)
) -> dict[str, list[str]]:
    year_str, month_str = month.split("-")
    return await calendar_view.month_events(user["id"], int(year_str), int(month_str))


# Индикатор "как прошёл день" в плитках месячного календаря (Phase 27) —
# средний балл вечерней рефлексии по дням, где она заполнена (см.
# calendar_view.month_diary_moods). Дневник — только у владельца (см.
# _NOT_READY_FOR_OTHERS выше) — остальные получают пустую карту, плитки
# просто не подсвечиваются, без ошибки.
@app.get("/miniapp/api/calendar/month-moods")
async def calendar_month_moods_endpoint(
    month: str, user: dict = Depends(get_authorized_user)
) -> dict[str, float]:
    if not _is_owner(user["id"]):
        return {}
    year_str, month_str = month.split("-")
    return await calendar_view.month_diary_moods(int(year_str), int(month_str))


# Дневник (Phase 26) — ревью прошедшего дня в расширенном экране; сам
# дневник по-прежнему только в Notion (Diary) и только у владельца (см.
# _NOT_READY_FOR_OTHERS) — тут просто читаем и фильтруем по дате на
# своей стороне (list_diary_entries — маленький датасет, без серверной
# фильтрации).
@app.get("/miniapp/api/diary/{entry_date}")
async def diary_day_endpoint(
    entry_date: str, user: dict = Depends(get_authorized_user)
) -> dict | None:
    if not _is_owner(user["id"]):
        raise HTTPException(status_code=403, detail=_NOT_READY_FOR_OTHERS)
    target = date.fromisoformat(entry_date)
    entries = await list_diary_entries()
    entry = next((e for e in entries if e["entry_date"] == target), None)
    if entry is None:
        return None
    return {
        "physical": entry["physical"],
        "social": entry["social"],
        "productivity": entry["productivity"],
        "happiness": entry["happiness"],
        "highlight": entry["highlight"],
    }


# Аналитика (Phase 24) — гант по проектам переиспользует уже готовый
# GET /miniapp/api/projects (task_count/done_count/start_date/end_date
# там уже есть), отдельного эндпоинта под него не заводим.
@app.get("/miniapp/api/analytics/spheres")
async def analytics_spheres_endpoint(user: dict = Depends(get_authorized_user)) -> list[dict]:
    return await analytics_repo.sphere_breakdown(user["id"])


@app.get("/miniapp/api/analytics/month")
async def analytics_month_endpoint(
    month: str | None = None, user: dict = Depends(get_authorized_user)
) -> dict:
    # month — тот же формат "YYYY-MM", что у /calendar/month (Phase 41,
    # график теперь листается по месяцам, а не только "этот месяц").
    # Без параметра — текущий месяц, как раньше.
    if month:
        year_str, month_str = month.split("-")
        anchor = date(int(year_str), int(month_str), 1)
    else:
        anchor = datetime.now(ZoneInfo(settings.timezone)).date()
    return await analytics_repo.month_breakdown(user["id"], anchor)


@app.get("/miniapp/api/analytics/summary")
async def analytics_summary_endpoint(user: dict = Depends(get_authorized_user)) -> dict:
    uid = user["id"]
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    spheres = await analytics_repo.sphere_breakdown(uid)
    month = await analytics_repo.month_breakdown(uid, today)
    projects = await projects_repo.list_projects(uid)
    text = await analyze_productivity(spheres, month, projects)
    return {"text": text}


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
