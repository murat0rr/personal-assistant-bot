import itertools
from datetime import date, datetime

from src.handlers.miniapp_tasks import build_task_board
from src.models.task import Task

# 2026-08-29 — суббота.
_TODAY = date(2026, 8, 29)
_YESTERDAY = date(2026, 8, 28)

_counter = itertools.count()


def _task(
    title: str,
    due_date: date | None,
    priority: str | None = None,
    done: bool = False,
    sort_order: float | None = None,
) -> Task:
    # due_date в модели — timestamp; здесь удобнее задавать в тестах просто
    # день, а на полночь переводим внутри (см. Task.due_date). sort_order по
    # умолчанию — по порядку вызова (имитирует "как создавали"), явно
    # передаём только там, где тест реально проверяет порядок.
    return Task(
        title=title,
        due_date=datetime.combine(due_date, datetime.min.time()) if due_date else None,
        priority=priority,
        done=done,
        sort_order=sort_order if sort_order is not None else next(_counter),
    )


def test_days_split_by_exact_due_date():
    tasks = [
        _task("вчера", _YESTERDAY),
        _task("сегодня", _TODAY),
        _task("позавчера", date(2026, 8, 20)),
        _task("без даты", None),
    ]
    board = build_task_board(tasks, _TODAY)
    assert [t["title"] for t in board["days"]["yesterday"]["tasks"]] == ["вчера"]
    assert [t["title"] for t in board["days"]["today"]["tasks"]] == ["сегодня"]
    assert board["days"]["yesterday"]["date"] == "2026-08-28"
    assert board["days"]["today"]["date"] == "2026-08-29"


def test_dated_tasks_includes_every_dated_task_any_range():
    tasks = [
        _task("далеко в прошлом", date(2020, 1, 1)),
        _task("далеко в будущем", date(2030, 1, 1)),
        _task("без даты", None),
    ]
    board = build_task_board(tasks, _TODAY)
    titles = {t["title"] for t in board["dated_tasks"]}
    assert titles == {"далеко в прошлом", "далеко в будущем"}


def test_inbox_includes_overdue_undone_and_all_undated():
    tasks = [
        _task("просрочена не сделана", date(2026, 8, 20), done=False),
        _task("просрочена сделана", date(2026, 8, 20), done=True),
        _task("будущая", date(2026, 9, 1)),
        _task("без даты не сделана", None, done=False),
        _task("без даты сделана", None, done=True),
    ]
    board = build_task_board(tasks, _TODAY)
    titles = {t["title"] for t in board["inbox"]}
    assert titles == {"просрочена не сделана", "без даты не сделана", "без даты сделана"}


def test_day_ordered_by_sort_order_marking_done_does_not_move_task():
    # Ручной порядок (Phase 13) — задан явно, не по приоритету. Отметка
    # "выполнено" не должна ничего переставлять.
    tasks = [
        _task("третья", _TODAY, priority="низкий", sort_order=3000),
        _task("первая, выполнена", _TODAY, priority="высокий", done=True, sort_order=1000),
        _task("вторая", _TODAY, priority="средний", sort_order=2000),
    ]
    board = build_task_board(tasks, _TODAY)
    titles = [t["title"] for t in board["days"]["today"]["tasks"]]
    assert titles == ["первая, выполнена", "вторая", "третья"]


def test_empty_board():
    board = build_task_board([], _TODAY)
    assert board["days"]["today"]["tasks"] == []
    assert board["inbox"] == []
    assert board["dated_tasks"] == []


def test_due_time_shown_only_when_not_midnight():
    with_time = Task(
        title="встреча",
        due_date=datetime(2026, 8, 29, 14, 30),
        priority="event",
        done=False,
        sort_order=1,
    )
    without_time = Task(
        title="обычная",
        due_date=datetime(2026, 8, 29, 0, 0),
        priority="средний",
        done=False,
        sort_order=2,
    )

    board = build_task_board([with_time, without_time], _TODAY)
    by_title = {t["title"]: t for t in board["dated_tasks"]}
    assert by_title["встреча"]["due_time"] == "14:30"
    assert by_title["встреча"]["due_date"] == "2026-08-29"
    assert by_title["обычная"]["due_time"] is None


def test_description_included_in_serialized_task():
    # Phase 65 — свободный текст, видимый только в форме редактирования,
    # но всё равно приходит в общей сериализации доски.
    with_description = Task(
        title="найти реферат",
        due_date=None,
        priority="средний",
        done=False,
        sort_order=1,
        description="Попробуй Википедию и школьную библиотеку.",
    )
    without_description = Task(
        title="купить хлеб", due_date=None, priority="средний", done=False, sort_order=2
    )

    board = build_task_board([with_description, without_description], _TODAY)
    by_title = {t["title"]: t for t in board["inbox"]}
    assert by_title["найти реферат"]["description"] == "Попробуй Википедию и школьную библиотеку."
    assert by_title["купить хлеб"]["description"] is None
