from datetime import date, datetime

from src.handlers.f5_morning_digest import build_morning_digest_text
from src.models.task import Task

_TODAY = date(2026, 8, 29)


def _task(
    title: str,
    due_date: date | None,
    due_time: tuple[int, int] | None = None,
    is_event: bool = False,
    source: str | None = None,
) -> Task:
    if due_date is None:
        due_datetime = None
    elif due_time is not None:
        due_datetime = datetime.combine(due_date, datetime.min.time()).replace(
            hour=due_time[0], minute=due_time[1]
        )
    else:
        due_datetime = datetime.combine(due_date, datetime.min.time())
    return Task(
        title=title,
        due_date=due_datetime,
        done=False,
        is_event=is_event,
        source=source,
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


def test_event_today_goes_to_separate_section_with_time():
    tasks = [
        _task("встреча с командой", _TODAY, due_time=(14, 0), is_event=True),
        _task("обычная задача", _TODAY),
    ]
    text = build_morning_digest_text(tasks, _TODAY)

    assert "🗓 События:" in text
    assert "— 14:00 встреча с командой" in text
    assert "📌 На сегодня:" in text
    assert "— обычная задача" in text


def test_task_without_time_has_no_time_prefix():
    tasks = [_task("обычная задача", _TODAY)]
    text = build_morning_digest_text(tasks, _TODAY)

    lines = [line for line in text.splitlines() if "обычная задача" in line]
    assert lines == ["— обычная задача"]


def test_recurring_task_gets_badge():
    tasks = [_task("зарядка", _TODAY, source="recurring")]
    text = build_morning_digest_text(tasks, _TODAY)

    assert "— 🔁 зарядка" in text


def test_recurring_task_with_time_shows_both():
    tasks = [_task("утренняя пробежка", _TODAY, due_time=(7, 30), source="recurring")]
    text = build_morning_digest_text(tasks, _TODAY)

    assert "— 07:30 🔁 утренняя пробежка" in text


def test_overdue_event_shows_time_and_date():
    tasks = [_task("пропущенная встреча", date(2026, 8, 28), due_time=(9, 0), is_event=True)]
    text = build_morning_digest_text(tasks, _TODAY)

    assert "— 09:00 пропущенная встреча (28.08)" in text


def test_events_today_sorted_by_time():
    tasks = [
        _task("позже", _TODAY, due_time=(18, 0), is_event=True),
        _task("раньше", _TODAY, due_time=(9, 0), is_event=True),
    ]
    text = build_morning_digest_text(tasks, _TODAY)

    assert text.index("раньше") < text.index("позже")
