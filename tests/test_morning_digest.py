from datetime import date, datetime

from src.handlers.f5_morning_digest import build_morning_digest_text
from src.models.task import Task

_TODAY = date(2026, 8, 29)


def _task(title: str, due_date: date | None) -> Task:
    return Task(
        title=title,
        due_date=datetime.combine(due_date, datetime.min.time()) if due_date else None,
        done=False,
    )


def test_empty_when_no_active_tasks():
    assert build_morning_digest_text([], _TODAY) == "🌅 Доброе утро! На сегодня активных задач нет."


def test_no_due_date_ignored():
    tasks = [_task("без срока", None)]
    assert (
        build_morning_digest_text(tasks, _TODAY) == "🌅 Доброе утро! На сегодня активных задач нет."
    )


def test_overdue_and_today_grouped():
    tasks = [
        _task("вчерашняя", date(2026, 8, 28)),
        _task("сегодняшняя", _TODAY),
        _task("будущая", date(2026, 8, 30)),
    ]
    text = build_morning_digest_text(tasks, _TODAY)

    assert "⚠️ Просрочено:" in text
    assert "— вчерашняя (28.08)" in text
    assert "📌 На сегодня:" in text
    assert "— сегодняшняя" in text
    assert "будущая" not in text


def test_overdue_sorted_oldest_first():
    tasks = [
        _task("свежая просрочка", date(2026, 8, 28)),
        _task("старая просрочка", date(2026, 8, 20)),
    ]
    text = build_morning_digest_text(tasks, _TODAY)

    assert text.index("старая просрочка") < text.index("свежая просрочка")
