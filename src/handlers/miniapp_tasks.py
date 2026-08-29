from datetime import date, timedelta

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


def _day_tasks(tasks: list[Task], target: date) -> list[dict]:
    return [
        _serialize(t) for t in sorted((t for t in tasks if t.due_date == target), key=_sort_key)
    ]


def build_task_board(tasks: list[Task], today: date) -> dict:
    """Три пролистываемых дня (вчера/сегодня/завтра) — строго по due_date,
    невыполненные сверху по приоритету, выполненные внизу. "Инбокс" —
    просроченные невыполненные задачи (любая дата в прошлом, не только
    вчера) + все задачи без даты, независимо от статуса. Чистая функция —
    тестируется офлайн, тот же паттерн, что build_morning_digest_text."""
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    inbox = sorted(
        (t for t in tasks if t.due_date is None or (t.due_date < today and not _is_done(t))),
        key=_sort_key,
    )

    return {
        "days": {
            "yesterday": {"date": yesterday.isoformat(), "tasks": _day_tasks(tasks, yesterday)},
            "today": {"date": today.isoformat(), "tasks": _day_tasks(tasks, today)},
            "tomorrow": {"date": tomorrow.isoformat(), "tasks": _day_tasks(tasks, tomorrow)},
        },
        "inbox": [_serialize(t) for t in inbox],
    }
