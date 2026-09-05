from datetime import datetime
from zoneinfo import ZoneInfo

from src.core.google_calendar_sync import _event_to_task_fields

_TZ = ZoneInfo("Europe/Moscow")


def test_timed_event_becomes_event_priority():
    event = {
        "id": "abc123",
        "summary": "Встреча с командой",
        "start": {"dateTime": "2026-09-10T14:30:00+03:00"},
    }
    fields = _event_to_task_fields(event, _TZ)
    assert fields == {
        "title": "Встреча с командой",
        "due_date": datetime(2026, 9, 10, 14, 30, 0),
        "priority": "event",
    }


def test_timed_event_converts_across_timezones():
    # UTC-время события, пользователь в Москве (+3) — итоговое время
    # должно быть в его часовом поясе, не как есть.
    event = {"id": "x", "summary": "Звонок", "start": {"dateTime": "2026-09-10T10:00:00Z"}}
    fields = _event_to_task_fields(event, _TZ)
    assert fields["due_date"] == datetime(2026, 9, 10, 13, 0, 0)


def test_all_day_event_has_no_time_and_no_event_priority():
    event = {"id": "y", "summary": "День рождения", "start": {"date": "2026-09-12"}}
    fields = _event_to_task_fields(event, _TZ)
    assert fields == {
        "title": "День рождения",
        "due_date": datetime(2026, 9, 12, 0, 0, 0),
        "priority": None,
    }


def test_cancelled_event_is_skipped():
    event = {
        "id": "z",
        "status": "cancelled",
        "summary": "Отменённая встреча",
        "start": {"dateTime": "2026-09-10T14:30:00+03:00"},
    }
    assert _event_to_task_fields(event, _TZ) is None


def test_missing_summary_gets_placeholder_title():
    event = {"id": "w", "start": {"date": "2026-09-12"}}
    fields = _event_to_task_fields(event, _TZ)
    assert fields["title"] == "(без названия)"


def test_event_without_start_is_skipped():
    event = {"id": "v", "summary": "Сломанное событие"}
    assert _event_to_task_fields(event, _TZ) is None
