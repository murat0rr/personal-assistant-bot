from datetime import date

from src.core.task_templates import _is_stale


def test_is_stale_never_used():
    # last_used_date=None — ни разу не пользовались, всегда "давно не делал"
    assert _is_stale(None, 14, date(2026, 8, 30)) is True


def test_is_stale_before_threshold():
    last_used = date(2026, 8, 20)
    today = date(2026, 8, 30)  # 10 дней назад, порог 14
    assert _is_stale(last_used, 14, today) is False


def test_is_stale_at_threshold():
    last_used = date(2026, 8, 16)
    today = date(2026, 8, 30)  # ровно 14 дней назад, порог 14 — уже устарел
    assert _is_stale(last_used, 14, today) is True


def test_is_stale_after_threshold():
    last_used = date(2026, 8, 1)
    today = date(2026, 8, 30)  # 29 дней назад, порог 14
    assert _is_stale(last_used, 14, today) is True


def test_is_stale_used_today():
    today = date(2026, 8, 30)
    assert _is_stale(today, 14, today) is False
