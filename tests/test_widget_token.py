import time

from src.core.config import settings
from src.core.web_session import create_session_token
from src.core.widget_token import create_widget_token, verify_widget_token


def test_valid_token_returns_user_id():
    settings.session_secret = "test-secret"
    token = create_widget_token(42)
    assert verify_widget_token(token) == 42


def test_tampered_signature_rejected():
    settings.session_secret = "test-secret"
    token = create_widget_token(42)
    payload, sig = token.rsplit(".", 1)
    tampered_sig = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert verify_widget_token(f"{payload}.{tampered_sig}") is None


def test_wrong_secret_rejected():
    settings.session_secret = "test-secret"
    token = create_widget_token(42)
    settings.session_secret = "other-secret"
    assert verify_widget_token(token) is None
    settings.session_secret = "test-secret"


def test_expired_token_rejected():
    settings.session_secret = "test-secret"
    token = create_widget_token(42)
    # Подделываем протухший exp напрямую — не ждать реальный год в тесте.
    import base64
    import hashlib
    import hmac
    import json

    payload = json.dumps({"wuid": 42, "exp": int(time.time()) - 10})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(
        settings.session_secret.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    expired_token = f"{payload_b64}.{sig}"
    assert verify_widget_token(expired_token) is None
    assert token  # sanity: исходный (не протухший) токен вообще был создан


def test_malformed_token_rejected():
    settings.session_secret = "test-secret"
    assert verify_widget_token("garbage") is None
    assert verify_widget_token("") is None


def test_create_token_refuses_empty_secret():
    import pytest

    settings.session_secret = ""
    try:
        with pytest.raises(RuntimeError):
            create_widget_token(42)
    finally:
        settings.session_secret = "test-secret"


def test_verify_token_rejects_when_secret_empty():
    settings.session_secret = "test-secret"
    token = create_widget_token(42)
    settings.session_secret = ""
    try:
        assert verify_widget_token(token) is None
    finally:
        settings.session_secret = "test-secret"


def test_session_token_not_accepted_as_widget_token():
    # Разные claim-формы ("uid" vs "wuid") — утечка одного типа токена
    # не должна давать доступ через другой канал, даже с тем же секретом.
    settings.session_secret = "test-secret"
    session_token = create_session_token(42)
    assert verify_widget_token(session_token) is None
