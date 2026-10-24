"""Долгоживущий токен для виджета на главном экране телефона
(Scriptable на iOS, Tasker на Android, 2026-10-25) — та же HMAC-схема,
что у `web_session.py`, но сознательно ОТДЕЛЬНАЯ функция, не
параметризация существующей: другой срок жизни (~год, не 30 дней) и
другая форма claim (`"wuid"`, не `"uid"`), чтобы утечка одного типа
токена не давала доступ через другой канал, и чтобы в коде было явно
видно, какой токен для чего.

Read-only потребитель (`src/adapters/widget_api.py`) — токен нигде не
даёт прав на запись, только на чтение списка задач на сегодня."""

import base64
import hashlib
import hmac
import json
import time

from src.core.config import settings

_WIDGET_TOKEN_MAX_AGE_SECONDS = 365 * 24 * 60 * 60  # ~1 год


def create_widget_token(user_id: int) -> str:
    if not settings.session_secret:
        raise RuntimeError("SESSION_SECRET не настроен — токен для виджета недоступен.")
    payload = json.dumps({"wuid": user_id, "exp": int(time.time()) + _WIDGET_TOKEN_MAX_AGE_SECONDS})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    signature = hmac.new(
        settings.session_secret.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_widget_token(token: str) -> int | None:
    """Возвращает user_id при валидной, не протухшей подписи — иначе None.
    Не бросает исключений ни на каком мусорном вводе (токен приходит от
    внешнего скрипта на телефоне — недоверенный ввод, тот же принцип,
    что verify_session_token/verify_miniapp_init_data)."""
    if not settings.session_secret:
        return None
    try:
        payload_b64, signature = token.rsplit(".", 1)
    except ValueError:
        return None

    expected_signature = hmac.new(
        settings.session_secret.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return None

    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        uid = int(payload["wuid"])
        exp = int(payload["exp"])
    except (ValueError, KeyError, TypeError):
        return None

    if time.time() > exp:
        return None
    return uid
