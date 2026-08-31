import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

_MAX_AUTH_AGE_SECONDS = 24 * 60 * 60


def verify_miniapp_init_data(init_data: str, bot_token: str) -> dict | None:
    """Проверить initData Telegram Mini App по алгоритму Telegram.

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    Возвращает распарсенный объект user при успехе, иначе None.
    """
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = pairs.get("auth_date")
    if not auth_date or time.time() - int(auth_date) > _MAX_AUTH_AGE_SECONDS:
        return None

    user_raw = pairs.get("user")
    if not user_raw:
        return None
    return json.loads(user_raw)
