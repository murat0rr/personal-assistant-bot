from datetime import datetime

from src.adapters.api import _parse_due_date


def test_parse_due_date_plain_date_goes_to_midnight():
    assert _parse_due_date("2026-09-01") == datetime(2026, 9, 1, 0, 0)


def test_parse_due_date_datetime_local_keeps_time():
    assert _parse_due_date("2026-09-01T14:30") == datetime(2026, 9, 1, 14, 30)
