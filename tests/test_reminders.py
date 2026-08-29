from datetime import UTC, date, datetime

from src.handlers.f_reminders import _is_due
from src.models.reminder import Reminder

_TODAY = date(2026, 8, 29)


def _reminder(kind: str, value: dict, last_fired_date: date | None = None) -> Reminder:
    return Reminder(
        id=1,
        text="тест",
        schedule_kind=kind,
        schedule_value=value,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_fired_date=last_fired_date,
    )


def test_once_due_on_matching_date():
    r = _reminder("once", {"date": "2026-08-29"})
    assert _is_due(r, _TODAY) is True


def test_once_not_due_other_date():
    r = _reminder("once", {"date": "2026-09-01"})
    assert _is_due(r, _TODAY) is False


def test_monthly_day_regular():
    r = _reminder("monthly_day", {"day": 29})
    assert _is_due(r, _TODAY) is True


def test_monthly_day_last_day_of_month():
    # 29 августа 2026 — не последний день месяца (в августе 31 день).
    r = _reminder("monthly_day", {"day": 32})
    assert _is_due(r, _TODAY) is False
    assert _is_due(r, date(2026, 8, 31)) is True


def test_monthly_day_last_day_short_month():
    # В сентябре 30 дней — day=32 срабатывает 30-го, не 31-го (его нет).
    r = _reminder("monthly_day", {"day": 32})
    assert _is_due(r, date(2026, 9, 30)) is True


def test_weekly_day_matches_weekday():
    # 2026-08-29 — суббота (weekday() == 5).
    r = _reminder("weekly_day", {"weekday": 5})
    assert _is_due(r, _TODAY) is True
    assert _is_due(r, date(2026, 8, 28)) is False


def test_interval_days_fires_on_anchor_and_multiples():
    r = _reminder("interval_days", {"interval_days": 5}, last_fired_date=date(2026, 8, 24))
    assert _is_due(r, date(2026, 8, 29)) is True
    assert _is_due(r, date(2026, 8, 27)) is False


def test_interval_days_uses_created_at_when_never_fired():
    r = Reminder(
        id=1,
        text="тест",
        schedule_kind="interval_days",
        schedule_value={"interval_days": 3},
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
        last_fired_date=None,
    )
    assert _is_due(r, date(2026, 8, 29)) is True
    assert _is_due(r, date(2026, 8, 28)) is False


def test_not_due_twice_same_day():
    r = _reminder("weekly_day", {"weekday": 5}, last_fired_date=_TODAY)
    assert _is_due(r, _TODAY) is False
