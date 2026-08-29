from datetime import date, timedelta

from src.models.task import Task

# "event" — то же самое поле priority, отдельное значение для задач-встреч
# со временем начала (не текстовый статус, а часть общего 4-значного набора
# приоритета — так проще: не нужна отдельная колонка/enum под один частный
# случай, и уже существующая сортировка/фильтрация по priority работает
# без изменений).
_PRIORITY_ORDER = {"высокий": 0, "event": 0, "средний": 1, "низкий": 2}


def _sort_key(task: Task) -> int:
    # Отмеченные задачи остаются на своём месте (не улетают вниз) — сортируем
    # только по приоритету, без группировки по статусу выполнения.
    return _PRIORITY_ORDER.get(task.priority, 3)


def _task_day(task: Task) -> date | None:
    return task.due_date.date() if task.due_date else None


def _task_time(task: Task) -> str | None:
    # Полночь — конвенция "время не указано" (вместо отдельного булева
    # флага под один частный случай — события без времени крайне редки).
    if task.due_date is None or (task.due_date.hour == 0 and task.due_date.minute == 0):
        return None
    return task.due_date.strftime("%H:%M")


def _serialize(task: Task) -> dict:
    day = _task_day(task)
    return {
        "id": task.id,
        "title": task.title,
        "due_date": day.isoformat() if day else None,
        "due_time": _task_time(task),
        "priority": task.priority,
        "done": task.done,
    }


def _day_tasks(tasks: list[Task], target: date) -> list[dict]:
    return [
        _serialize(t) for t in sorted((t for t in tasks if _task_day(t) == target), key=_sort_key)
    ]


def build_task_board(tasks: list[Task], today: date) -> dict:
    """ "Вчера"/"Сегодня" — строго по дате (без времени) due_date, сортировка
    только по приоритету (отмеченные задачи остаются на месте, не переезжают
    вниз). dated_tasks — вообще все задачи с проставленной датой (не только
    ближайшая неделя) — навигация по неделям в календаре Mini App работает
    из этого списка целиком на фронтенде, без похода в сеть при свайпе.
    "Инбокс" — просроченные невыполненные задачи (любая дата в прошлом) +
    все задачи без даты, независимо от статуса. Чистая функция —
    тестируется офлайн, тот же паттерн, что build_morning_digest_text."""
    yesterday = today - timedelta(days=1)

    inbox = sorted(
        (t for t in tasks if _task_day(t) is None or (_task_day(t) < today and not t.done)),
        key=_sort_key,
    )
    dated = sorted((t for t in tasks if _task_day(t) is not None), key=_sort_key)

    return {
        "days": {
            "yesterday": {"date": yesterday.isoformat(), "tasks": _day_tasks(tasks, yesterday)},
            "today": {"date": today.isoformat(), "tasks": _day_tasks(tasks, today)},
        },
        "dated_tasks": [_serialize(t) for t in dated],
        "inbox": [_serialize(t) for t in inbox],
    }
