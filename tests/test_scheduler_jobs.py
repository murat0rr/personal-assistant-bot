from src.scheduler.jobs import _job_specs

# _job_specs не трогает БД/Bot напрямую — строит список кортежей из уже
# разрешённых параметров (см. src/scheduler/jobs.py) — тестируется без
# похода в Postgres, тем же принципом, что _is_due/_should_send_nudge в
# других модулях. bot/storage здесь — просто значения, которые кладутся
# в args без проверки типа, сгодится что угодно узнаваемое.

_BOT = "fake-bot"
_STORAGE = "fake-storage"


def _spec_by_name(specs, name, user_id):
    return next(s for s in specs if s[0] == f"{name}:{user_id}")


def test_morning_digest_uses_custom_hour():
    specs = _job_specs(_BOT, _STORAGE, 111, "Europe/Moscow", morning_hour=9, evening_hour=21)
    _, _, trigger, _ = _spec_by_name(specs, "morning_digest", 111)
    assert trigger["hour"] == 9
    assert trigger["minute"] == 0


def test_morning_digest_defaults_to_eight_when_called_with_default():
    specs = _job_specs(_BOT, _STORAGE, 111, "Europe/Moscow", morning_hour=8, evening_hour=21)
    _, _, trigger, _ = _spec_by_name(specs, "morning_digest", 111)
    assert trigger["hour"] == 8


def test_evening_diary_uses_custom_hour_for_owner():
    from src.core.config import settings

    owner_id = settings.telegram_user_id
    specs = _job_specs(_BOT, _STORAGE, owner_id, "Europe/Moscow", morning_hour=8, evening_hour=22)
    _, _, trigger, _ = _spec_by_name(specs, "evening_diary", owner_id)
    assert trigger["hour"] == 22


def test_evening_diary_absent_for_non_owner():
    from src.core.config import settings

    non_owner = settings.telegram_user_id + 1
    specs = _job_specs(_BOT, _STORAGE, non_owner, "Europe/Moscow", morning_hour=8, evening_hour=21)
    assert not any(s[0] == f"evening_diary:{non_owner}" for s in specs)


def test_all_triggers_carry_the_given_timezone():
    specs = _job_specs(_BOT, _STORAGE, 111, "America/New_York", morning_hour=8, evening_hour=21)
    assert all(trigger["timezone"] == "America/New_York" for _, _, trigger, _ in specs)


def test_job_ids_are_unique_per_user():
    specs = _job_specs(_BOT, _STORAGE, 222, "Europe/Moscow", morning_hour=8, evening_hour=21)
    ids = [s[0] for s in specs]
    assert len(ids) == len(set(ids))
    assert all(job_id.endswith(":222") for job_id in ids)
