from datetime import date, timedelta

from src.handlers.f8_habits import _next_streak

_TODAY = date(2026, 8, 29)
_YESTERDAY = _TODAY - timedelta(days=1)


def test_streak_continues_from_yesterday():
    assert _next_streak(5, _YESTERDAY, _TODAY) == 6


def test_streak_resets_after_gap():
    assert _next_streak(5, date(2026, 8, 20), _TODAY) == 1


def test_streak_starts_from_zero_when_never_checked():
    assert _next_streak(0, None, _TODAY) == 1


def test_streak_unchanged_when_already_checked_today():
    assert _next_streak(5, _TODAY, _TODAY) == 5
