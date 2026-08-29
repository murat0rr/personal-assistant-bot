from datetime import date

from src.handlers.miniapp_tasks import build_task_board
from src.models.task import Task

# 2026-08-29 — суббота.
_TODAY = date(2026, 8, 29)
_YESTERDAY = date(2026, 8, 28)


def _task(
    title: str,
    due_date: date | None,
    priority: str | None = None,
    status: str = "Not started",
) -> Task:
    return Task(
        notion_page_id=title,
        title=title,
        due_date=due_date,
        priority=priority,
        status=status,
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
        _task("просрочена не сделана", date(2026, 8, 20), status="Not started"),
        _task("просрочена сделана", date(2026, 8, 20), status="Done"),
        _task("будущая", date(2026, 9, 1)),
        _task("без даты не сделана", None, status="Not started"),
        _task("без даты сделана", None, status="Done"),
    ]
    board = build_task_board(tasks, _TODAY)
    titles = {t["title"] for t in board["inbox"]}
    assert titles == {"просрочена не сделана", "без даты не сделана", "без даты сделана"}


def test_day_sorted_by_priority_only_done_stays_in_place():
    tasks = [
        _task("низкий", _TODAY, priority="низкий"),
        _task("высокий выполнена", _TODAY, priority="высокий", status="Done"),
        _task("средний", _TODAY, priority="средний"),
    ]
    board = build_task_board(tasks, _TODAY)
    titles = [t["title"] for t in board["days"]["today"]["tasks"]]
    # Выполненная задача с высоким приоритетом остаётся наверху, не улетает вниз.
    assert titles == ["высокий выполнена", "средний", "низкий"]


def test_empty_board():
    board = build_task_board([], _TODAY)
    assert board["days"]["today"]["tasks"] == []
    assert board["inbox"] == []
    assert board["dated_tasks"] == []
