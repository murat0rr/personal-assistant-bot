from datetime import date

from src.handlers.miniapp_tasks import build_task_board
from src.models.task import Task

_TODAY = date(2026, 8, 29)


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


def test_today_only_includes_tasks_due_today():
    tasks = [
        _task("сегодня", _TODAY),
        _task("завтра", date(2026, 8, 30)),
        _task("вчера", date(2026, 8, 28)),
        _task("без даты", None),
    ]
    board = build_task_board(tasks, _TODAY)
    assert [t["title"] for t in board["today"]] == ["сегодня"]


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


def test_today_sorted_by_priority_undone_first():
    tasks = [
        _task("низкий", _TODAY, priority="низкий"),
        _task("высокий", _TODAY, priority="высокий"),
        _task("выполнена", _TODAY, priority="высокий", status="Done"),
    ]
    board = build_task_board(tasks, _TODAY)
    titles = [t["title"] for t in board["today"]]
    assert titles == ["высокий", "низкий", "выполнена"]


def test_empty_board():
    assert build_task_board([], _TODAY) == {"today": [], "inbox": []}
