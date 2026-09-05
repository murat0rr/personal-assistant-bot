import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.core import google_calendar_sync as gcs
from src.core.google_calendar_sync import _event_to_task_fields

_TZ = ZoneInfo("Europe/Moscow")


def test_timed_event_becomes_is_event():
    event = {
        "id": "abc123",
        "summary": "Встреча с командой",
        "start": {"dateTime": "2026-09-10T14:30:00+03:00"},
    }
    fields = _event_to_task_fields(event, _TZ)
    assert fields == {
        "title": "Встреча с командой",
        "due_date": datetime(2026, 9, 10, 14, 30, 0),
        "priority": "средний",
        "is_event": True,
    }


def test_timed_event_converts_across_timezones():
    # UTC-время события, пользователь в Москве (+3) — итоговое время
    # должно быть в его часовом поясе, не как есть.
    event = {"id": "x", "summary": "Звонок", "start": {"dateTime": "2026-09-10T10:00:00Z"}}
    fields = _event_to_task_fields(event, _TZ)
    assert fields["due_date"] == datetime(2026, 9, 10, 13, 0, 0)


def test_all_day_event_has_no_time_and_is_not_event():
    event = {"id": "y", "summary": "День рождения", "start": {"date": "2026-09-12"}}
    fields = _event_to_task_fields(event, _TZ)
    assert fields == {
        "title": "День рождения",
        "due_date": datetime(2026, 9, 12, 0, 0, 0),
        "priority": "средний",
        "is_event": False,
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


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_maybe_sync_now_skips_second_call_within_cooldown(monkeypatch):
    calls = []

    async def fake_sync(bot, user_id):
        calls.append(user_id)

    monkeypatch.setattr(gcs, "sync_user_calendar", fake_sync)
    gcs._last_manual_sync.clear()

    await gcs.maybe_sync_now(1)
    await gcs.maybe_sync_now(1)

    assert calls == [1]


async def test_maybe_sync_now_allows_call_after_cooldown_elapsed(monkeypatch):
    calls = []

    async def fake_sync(bot, user_id):
        calls.append(user_id)

    monkeypatch.setattr(gcs, "sync_user_calendar", fake_sync)
    gcs._last_manual_sync.clear()
    gcs._last_manual_sync[2] = time.time() - gcs._MANUAL_SYNC_COOLDOWN_SECONDS - 1

    await gcs.maybe_sync_now(2)

    assert calls == [2]


async def test_maybe_sync_now_swallows_sync_errors(monkeypatch):
    async def failing_sync(bot, user_id):
        raise RuntimeError("сбой похода в Google")

    monkeypatch.setattr(gcs, "sync_user_calendar", failing_sync)
    gcs._last_manual_sync.clear()

    await gcs.maybe_sync_now(3)  # не должно бросить исключение наружу
