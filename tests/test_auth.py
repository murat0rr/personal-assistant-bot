from src.core.auth import is_authorized
from src.core.config import settings


def test_authorized_user_allowed():
    assert is_authorized(settings.telegram_user_id) is True


def test_other_user_denied():
    assert is_authorized(settings.telegram_user_id + 1) is False
