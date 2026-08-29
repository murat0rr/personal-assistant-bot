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


def build_task_board(tasks: list[Task]) -> dict:
    """Разбить задачи на "на день" (есть дата) и "без даты", в каждой группе
    невыполненные сверху по приоритету, выполненные — внизу. Чистая функция —
    тестируется офлайн, тот же паттерн, что build_morning_digest_text."""
    dated = sorted((t for t in tasks if t.due_date is not None), key=_sort_key)
    undated = sorted((t for t in tasks if t.due_date is None), key=_sort_key)
    return {
        "dated": [_serialize(t) for t in dated],
        "undated": [_serialize(t) for t in undated],
    }
