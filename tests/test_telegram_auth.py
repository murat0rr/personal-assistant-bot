import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from src.core.telegram_auth import verify_miniapp_init_data, verify_telegram_login_widget_data

_BOT_TOKEN = "123456:test-bot-token"


def _build_init_data(
    bot_token: str, *, user_id: int = 736839539, auth_date: int | None = None
) -> str:
    if auth_date is None:
        auth_date = int(time.time())
    user = json.dumps({"id": user_id, "first_name": "Test"})
    pairs = {"auth_date": str(auth_date), "query_id": "AAA", "user": user}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    pairs["hash"] = computed_hash
    return urlencode(pairs)


def test_valid_init_data_returns_user():
    init_data = _build_init_data(_BOT_TOKEN, user_id=42)
    user = verify_miniapp_init_data(init_data, _BOT_TOKEN)
    assert user == {"id": 42, "first_name": "Test"}


def test_wrong_bot_token_rejected():
    init_data = _build_init_data(_BOT_TOKEN)
    assert verify_miniapp_init_data(init_data, "other-token") is None


def test_tampered_field_rejected():
    init_data = _build_init_data(_BOT_TOKEN)
    tampered = init_data.replace("query_id=AAA", "query_id=BBB")
    assert verify_miniapp_init_data(tampered, _BOT_TOKEN) is None


def test_stale_auth_date_rejected():
    old_auth_date = int(time.time()) - 25 * 60 * 60
    init_data = _build_init_data(_BOT_TOKEN, auth_date=old_auth_date)
    assert verify_miniapp_init_data(init_data, _BOT_TOKEN) is None


def test_missing_hash_rejected():
    assert verify_miniapp_init_data("auth_date=1&user=%7B%7D", _BOT_TOKEN) is None


# ---- Telegram Login Widget (Phase 45) — алгоритм подписи отличается от
# Mini App initData выше (secret_key — прямой SHA-256 токена, без
# HMAC-обёртки "WebAppData"), поэтому свой хелпер сборки данных.


def _build_widget_data(
    bot_token: str, *, user_id: int = 736839539, auth_date: int | None = None
) -> dict:
    if auth_date is None:
        auth_date = int(time.time())
    pairs = {"id": str(user_id), "first_name": "Test", "auth_date": str(auth_date)}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return {**pairs, "hash": computed_hash}


def test_valid_widget_data_returns_pairs():
    data = _build_widget_data(_BOT_TOKEN, user_id=42)
    result = verify_telegram_login_widget_data(data, _BOT_TOKEN)
    assert result is not None
    assert result["id"] == "42"


def test_widget_wrong_bot_token_rejected():
    data = _build_widget_data(_BOT_TOKEN)
    assert verify_telegram_login_widget_data(data, "other-token") is None


def test_widget_tampered_field_rejected():
    data = _build_widget_data(_BOT_TOKEN)
    data["first_name"] = "Tampered"
    assert verify_telegram_login_widget_data(data, _BOT_TOKEN) is None


def test_widget_stale_auth_date_rejected():
    old_auth_date = int(time.time()) - 25 * 60 * 60
    data = _build_widget_data(_BOT_TOKEN, auth_date=old_auth_date)
    assert verify_telegram_login_widget_data(data, _BOT_TOKEN) is None


def test_widget_missing_hash_rejected():
    assert verify_telegram_login_widget_data({"id": "1", "auth_date": "1"}, _BOT_TOKEN) is None
