from datetime import date

from src.integrations.notion import DONE_STATUS_CANDIDATES
from src.models.task import Task

_PRIORITY_ORDER = {"высокий": 0, "средний": 1, "низкий": 2}


def _is_done(task: Task) -> bool:
    return task.status.lower() in DONE_STATUS_CANDIDATES


def _sort_key(task: Task) -> tuple[bool, int]:
    return (_is_done(task), _PRIORITY_ORDER.get(task.priority, 3))


def _serialize(task: Task) -> dict:
    return {
        "notion_page_id": task.notion_page_id,
        "title": task.title,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "priority": task.priority,
        "status": task.status,
        "done": _is_done(task),
    }


def build_task_board(tasks: list[Task], today: date) -> dict:
    """ "Задачи на день" — строго due_date == today, невыполненные сверху по
    приоритету, выполненные внизу. "Инбокс" — просроченные невыполненные
    задачи + вообще все задачи без даты (независимо от статуса). Чистая
    функция — тестируется офлайн, тот же паттерн, что build_morning_digest_text."""
    todays = sorted((t for t in tasks if t.due_date == today), key=_sort_key)
    inbox = sorted(
        (t for t in tasks if t.due_date is None or (t.due_date < today and not _is_done(t))),
        key=_sort_key,
    )
    return {
        "today": [_serialize(t) for t in todays],
        "inbox": [_serialize(t) for t in inbox],
    }
