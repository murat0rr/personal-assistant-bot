from datetime import UTC, datetime, timedelta

from src.handlers.f_task_nag import _should_delete_nudge, _should_send_nudge

_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


# ---- _should_send_nudge — формула X+N (Phase 59, подтверждена
# пользователем): при интервале X часов — 1-й намёк через X часов
# бездействия, 2-й — ещё через (X+1) час после первого, 3-й — через
# (X+2) после второго и т.д. last_event_at сдвигается на момент
# отправки каждого намёка (см. check_and_nudge), поэтому здесь
# "last_event_at" — это всегда "момент последнего события" (выполнение
# задачи ИЛИ предыдущий намёк), не исходное бездействие.


def test_first_nudge_fires_exactly_at_interval():
    # X=2, N=0 (ни одного намёка ещё не было) — порог ровно X часов.
    last_event_at = _NOW - timedelta(hours=2)
    assert _should_send_nudge(_NOW, last_event_at, interval_hours=2, streak_count=0) is True


def test_first_nudge_not_yet_due():
    last_event_at = _NOW - timedelta(hours=1, minutes=59)
    assert _should_send_nudge(_NOW, last_event_at, interval_hours=2, streak_count=0) is False


def test_second_nudge_waits_interval_plus_one():
    # X=2, N=1 (один намёк уже был) — следующий порог X+1=3 часа от
    # МОМЕНТА ПЕРВОГО НАМЁКА (last_event_at уже сдвинут на него).
    last_event_at = _NOW - timedelta(hours=3)
    assert _should_send_nudge(_NOW, last_event_at, interval_hours=2, streak_count=1) is True


def test_second_nudge_not_yet_due():
    last_event_at = _NOW - timedelta(hours=2, minutes=59)
    assert _should_send_nudge(_NOW, last_event_at, interval_hours=2, streak_count=1) is False


def test_third_nudge_waits_interval_plus_two():
    # X=2, N=2 — порог X+2=4 часа от момента второго намёка.
    last_event_at = _NOW - timedelta(hours=4)
    assert _should_send_nudge(_NOW, last_event_at, interval_hours=2, streak_count=2) is True


# ---- _should_delete_nudge — 59 минут после отправки, независимо от
# streak_count/enabled (проверяется отдельно в check_and_nudge).


def test_nudge_deleted_after_59_minutes():
    sent_at = _NOW - timedelta(minutes=59)
    assert _should_delete_nudge(_NOW, sent_at) is True


def test_nudge_not_deleted_before_59_minutes():
    sent_at = _NOW - timedelta(minutes=58)
    assert _should_delete_nudge(_NOW, sent_at) is False


def test_no_pending_deletion_when_never_sent():
    assert _should_delete_nudge(_NOW, None) is False
