from datetime import date

from src.scheduler.jobs import _month_bounds, _quarter_bounds, _week_bounds, _year_bounds


def test_week_bounds_from_sunday():
    # Джоба стреляет по воскресеньям — "предстоящая неделя" начинается
    # завтра.
    sunday = date(2026, 8, 30)
    start, end = _week_bounds(sunday)
    assert start == date(2026, 8, 31)  # понедельник
    assert end == date(2026, 9, 6)  # воскресенье


def test_month_bounds_regular():
    start, end = _month_bounds(date(2026, 8, 2))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 31)


def test_month_bounds_february_leap_year():
    start, end = _month_bounds(date(2028, 2, 2))
    assert start == date(2028, 2, 1)
    assert end == date(2028, 2, 29)


def test_month_bounds_february_non_leap_year():
    start, end = _month_bounds(date(2026, 2, 2))
    assert start == date(2026, 2, 1)
    assert end == date(2026, 2, 28)


def test_quarter_bounds_q1():
    start, end = _quarter_bounds(date(2026, 1, 3))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 3, 31)


def test_quarter_bounds_q3():
    start, end = _quarter_bounds(date(2026, 7, 3))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 9, 30)


def test_quarter_bounds_q4():
    start, end = _quarter_bounds(date(2026, 10, 3))
    assert start == date(2026, 10, 1)
    assert end == date(2026, 12, 31)


def test_year_bounds():
    start, end = _year_bounds(date(2026, 1, 4))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 12, 31)
