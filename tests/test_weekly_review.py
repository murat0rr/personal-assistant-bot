from datetime import UTC, date, datetime

from src.handlers.f11_weekly_review import build_weekly_review_text
from src.models.task import Task

_TODAY = date(2026, 8, 29)
_WEEK_START = date(2026, 8, 22)


def _task(status: str, due_date: date | None = None, updated_at: datetime | None = None) -> Task:
    return Task(
        notion_page_id=status + str(due_date) + str(updated_at),
        title="задача",
        due_date=due_date,
        status=status,
        updated_at=updated_at,
    )


def _diary(entry_date: date, **ratings) -> dict:
    return {
        "entry_date": entry_date,
        "physical": ratings.get("physical"),
        "social": ratings.get("social"),
        "productivity": ratings.get("productivity"),
        "happiness": ratings.get("happiness"),
        "highlight": ratings.get("highlight"),
    }


def test_empty_week():
    text = build_weekly_review_text([], [], [], _WEEK_START, _TODAY)
    assert "выполнено 0, просрочено 0" in text
    assert "записей за неделю нет" in text


def test_counts_done_this_week_and_overdue():
    tasks = [
        _task(
            "Done",
            updated_at=datetime(2026, 8, 24, tzinfo=UTC),
        ),
        _task(
            "Done",
            updated_at=datetime(2026, 8, 10, tzinfo=UTC),
        ),  # выполнено раньше этой недели — не считаем
        _task("Not started", due_date=date(2026, 8, 20)),  # просрочено
        _task("Not started", due_date=date(2026, 9, 1)),  # ещё не просрочено
    ]
    text = build_weekly_review_text(tasks, [], [], _WEEK_START, _TODAY)
    assert "выполнено 1, просрочено 1" in text


def test_diary_averages_and_highlights():
    entries = [
        _diary(date(2026, 8, 23), physical=2, happiness=3, highlight="сходил в спортзал"),
        _diary(date(2026, 8, 25), physical=4, happiness=1),
        _diary(date(2026, 8, 15), physical=5, happiness=5),  # вне недели — не считаем
    ]
    text = build_weekly_review_text([], entries, [], _WEEK_START, _TODAY)
    assert "2 записей за неделю" in text
    assert "physical: 3.0" in text
    assert "happiness: 2.0" in text
    assert "сходил в спортзал" in text


def test_habits_listed_with_streak():
    habits = [{"name": "спорт", "streak": 5}, {"name": "чтение", "streak": 0}]
    text = build_weekly_review_text([], [], habits, _WEEK_START, _TODAY)
    assert "— спорт: 5 дн. подряд" in text
    assert "— чтение: 0 дн. подряд" in text
