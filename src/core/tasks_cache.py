"""Кэш сырого списка задач пользователя (Redis, cache-aside) — ускоряет
главный экран Mini App (`GET /miniapp/api/tasks`). Кэшируем результат
SELECT ДО группировки по дням (`build_task_board`,
src/handlers/miniapp_tasks.py) — группировка зависит от "сегодня",
которое меняется каждые сутки, и не должна застывать на 2 суток TTL.
Инвалидация — на каждой мутации `tasks` (см. все вызовы
`invalidate_tasks_cache` по кодбейзу), не на TTL: TTL здесь — только
подстраховка "не висеть вечно", если где-то забыли инвалидировать.

Тот же паттерн lazy-singleton клиента, что уже в login_codes.py/
google_oauth_state.py/f_set_day_task.py. Все операции — best-effort:
недоступный Redis не должен ронять загрузку главного экрана, только
откатывать её на обычный путь через БД.
"""

import json
import logging
from datetime import datetime

import redis.asyncio as redis

from src.core.config import settings
from src.models.task import Task

logger = logging.getLogger(__name__)

_redis: redis.Redis | None = None
_TTL_SECONDS = 2 * 24 * 60 * 60  # 2 суток


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        # Короткий таймаут на подключение/операцию (в отличие от
        # login_codes.py/google_oauth_state.py, где дефолтный клиент
        # без таймаута): там недоступный Redis ломает конкретное
        # действие (вход по коду, OAuth) — здесь же смысл всей фичи в
        # скорости главного экрана, а дефолтный TCP-таймаут на
        # мёртвый Redis оказался ~4с живьём (жил бы незаметно для
        # пользователя как "подвисание", несмотря на best-effort
        # try/except ниже, который спасает только от падения, не от
        # задержки).
        _redis = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _redis


def _key(user_id: int) -> str:
    return f"tasks_raw:{user_id}"


# Поля, которые реально читают build_task_board/serialize_task
# (src/handlers/miniapp_tasks.py) — ровно они и сериализуются, user_id/
# archived не нужны: кэшируем уже отфильтрованный по ним результат.
_FIELDS = (
    "id",
    "title",
    "priority",
    "done",
    "sort_order",
    "project_id",
    "sphere",
    "description",
    "is_event",
    "source",
    "recurring_rule_id",
    "duration_minutes",
)


def _to_row(task: Task) -> dict:
    return {
        **{f: getattr(task, f) for f in _FIELDS},
        "due_date": task.due_date.isoformat() if task.due_date else None,
    }


def _from_row(row: dict) -> Task:
    row = dict(row)
    due_date = row.pop("due_date")
    return Task(due_date=datetime.fromisoformat(due_date) if due_date else None, **row)


async def get_cached_tasks(user_id: int) -> list[Task] | None:
    """None — промах или Redis недоступен (кэш best-effort, никогда не
    должен ронять загрузку главного экрана)."""
    try:
        raw = await _get_redis().get(_key(user_id))
        if raw is None:
            return None
        return [_from_row(row) for row in json.loads(raw)]
    except Exception:
        logger.exception("Не удалось прочитать кэш задач для %s", user_id)
        return None


async def set_cached_tasks(user_id: int, tasks: list[Task]) -> None:
    try:
        payload = json.dumps([_to_row(t) for t in tasks])
        await _get_redis().set(_key(user_id), payload, ex=_TTL_SECONDS)
    except Exception:
        logger.exception("Не удалось записать кэш задач для %s", user_id)


async def invalidate_tasks_cache(user_id: int) -> None:
    try:
        await _get_redis().delete(_key(user_id))
    except Exception:
        logger.exception("Не удалось сбросить кэш задач для %s", user_id)
