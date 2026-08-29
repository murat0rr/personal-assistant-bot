from datetime import date, timedelta

from src.integrations.notion import DONE_STATUS_CANDIDATES
from src.models.task import Task

_PRIORITY_ORDER = {"высокий": 0, "средний": 1, "низкий": 2}


def _is_done(task: Task) -> bool:
    return task.status.lower() in DONE_STATUS_CANDIDATES


def _sort_key(task: Task) -> int:
    # Отмеченные задачи остаются на своём месте (не улетают вниз) — сортируем
    # только по приоритету, без группировки по статусу выполнения.
    return _PRIORITY_ORDER.get(task.priority, 3)


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
    """ "Вчера"/"Сегодня" — строго по due_date, сортировка только по
    приоритету (отмеченные задачи остаются на месте, не переезжают вниз).
    "Неделя" — текущая календарная неделя (Пн-Вс), задачи по каждому дню, для
    карточки-календаря в Mini App. "Инбокс" — просроченные невыполненные
    задачи (любая дата в прошлом) + все задачи без даты, независимо от
    статуса. Чистая функция — тестируется офлайн, тот же паттерн, что
    build_morning_digest_text."""
    yesterday = today - timedelta(days=1)
    monday = today - timedelta(days=today.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]

    inbox = sorted(
        (t for t in tasks if t.due_date is None or (t.due_date < today and not _is_done(t))),
        key=_sort_key,
    )

    return {
        "days": {
            "yesterday": {"date": yesterday.isoformat(), "tasks": _day_tasks(tasks, yesterday)},
            "today": {"date": today.isoformat(), "tasks": _day_tasks(tasks, today)},
        },
        "week": {d.isoformat(): _day_tasks(tasks, d) for d in week_dates},
        "inbox": [_serialize(t) for t in inbox],
    }
