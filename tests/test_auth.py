from src.core.auth import _is_primary_owner
from src.core.config import settings


def test_primary_owner_allowed():
    assert _is_primary_owner(settings.telegram_user_id) is True


def test_other_user_not_primary_owner():
    assert _is_primary_owner(settings.telegram_user_id + 1) is False
