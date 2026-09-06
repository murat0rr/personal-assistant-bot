from datetime import date, datetime

from src.core.recurring_tasks import _is_due
from src.models.recurring_task_rule import RecurringTaskRule


def _rule(
    kind: str,
    value: dict,
    last_materialized: date | None = None,
    created: date = date(2026, 1, 1),
    period_start: date | None = None,
    period_end: date | None = None,
):
    return RecurringTaskRule(
        title="тест",
        schedule_kind=kind,
        schedule_value=value,
        last_materialized_date=last_materialized,
        created_at=datetime.combine(created, datetime.min.time()),
        period_start=period_start,
        period_end=period_end,
    )


def test_weekly_day_matches():
    monday = date(2026, 8, 31)  # понедельник
    rule = _rule("weekly_day", {"weekday": 0})
    assert _is_due(rule, monday) is True


def test_weekly_day_does_not_match():
    tuesday = date(2026, 9, 1)
    rule = _rule("weekly_day", {"weekday": 0})
    assert _is_due(rule, tuesday) is False


def test_monthly_day_matches():
    rule = _rule("monthly_day", {"day": 5})
    assert _is_due(rule, date(2026, 9, 5)) is True
    assert _is_due(rule, date(2026, 9, 6)) is False


def test_monthly_day_last_day_of_month():
    rule = _rule("monthly_day", {"day": 32})
    assert _is_due(rule, date(2026, 9, 30)) is True
    assert _is_due(rule, date(2026, 9, 29)) is False


def test_interval_days_from_creation():
    rule = _rule("interval_days", {"interval_days": 3}, created=date(2026, 8, 1))
    assert _is_due(rule, date(2026, 8, 4)) is True  # +3 дня
    assert _is_due(rule, date(2026, 8, 3)) is False


def test_already_materialized_today_is_not_due_again():
    today = date(2026, 8, 31)
    rule = _rule("weekly_day", {"weekday": 0}, last_materialized=today)
    assert _is_due(rule, today) is False


# weekly_days (Phase 73, фидбек) — несколько дней недели одним правилом
# ("по будням"/"по выходным"/произвольный набор), в отличие от
# weekly_day (единственное число) выше, которое остаётся для уже
# существующих правил.
def test_weekly_days_matches_any_listed_day():
    rule = _rule("weekly_days", {"weekdays": [0, 2, 4]})  # Пн/Ср/Пт
    assert _is_due(rule, date(2026, 8, 31)) is True  # понедельник
    assert _is_due(rule, date(2026, 9, 1)) is False  # вторник


def test_weekly_days_weekend_preset():
    rule = _rule("weekly_days", {"weekdays": [5, 6]})  # Сб/Вс
    assert _is_due(rule, date(2026, 9, 5)) is True  # суббота
    assert _is_due(rule, date(2026, 9, 7)) is False  # понедельник


# Период действия (Phase 73, фидбек) — start/end независимы от паттерна,
# проверяются раньше него.
def test_period_start_blocks_before_start():
    rule = _rule("weekly_day", {"weekday": 0}, period_start=date(2026, 9, 7))
    assert _is_due(rule, date(2026, 8, 31)) is False  # понедельник, но раньше начала
    assert _is_due(rule, date(2026, 9, 7)) is True


def test_period_end_blocks_after_end():
    rule = _rule("weekly_day", {"weekday": 0}, period_end=date(2026, 9, 1))
    assert _is_due(rule, date(2026, 8, 31)) is True
    assert _is_due(rule, date(2026, 9, 7)) is False  # понедельник, но позже конца


def test_no_period_bounds_means_unlimited():
    rule = _rule("monthly_day", {"day": 1})
    assert _is_due(rule, date(2020, 1, 1)) is True
    assert _is_due(rule, date(2099, 1, 1)) is True
