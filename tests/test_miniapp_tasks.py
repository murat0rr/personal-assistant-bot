from datetime import date

from src.handlers.miniapp_tasks import build_task_board
from src.models.task import Task


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


def test_splits_dated_and_undated():
    tasks = [
        _task("с датой", date(2026, 8, 29)),
        _task("без даты", None),
    ]
    board = build_task_board(tasks)
    assert [t["title"] for t in board["dated"]] == ["с датой"]
    assert [t["title"] for t in board["undated"]] == ["без даты"]


def test_dated_sorted_by_priority_undone_first():
    tasks = [
        _task("низкий", date(2026, 8, 29), priority="низкий"),
        _task("высокий", date(2026, 8, 29), priority="высокий"),
        _task("средний", date(2026, 8, 29), priority="средний"),
        _task("без приоритета", date(2026, 8, 29), priority=None),
    ]
    board = build_task_board(tasks)
    titles = [t["title"] for t in board["dated"]]
    assert titles == ["высокий", "средний", "низкий", "без приоритета"]


def test_done_tasks_pushed_to_bottom():
    tasks = [
        _task("выполнено", date(2026, 8, 29), priority="высокий", status="Done"),
        _task("не выполнено", date(2026, 8, 29), priority="низкий", status="Not started"),
    ]
    board = build_task_board(tasks)
    titles = [t["title"] for t in board["dated"]]
    assert titles == ["не выполнено", "выполнено"]
    assert board["dated"][0]["done"] is False
    assert board["dated"][1]["done"] is True


def test_empty_board():
    assert build_task_board([]) == {"dated": [], "undated": []}
