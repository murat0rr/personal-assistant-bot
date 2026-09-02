"""Подписанная сессионная кука для веб-версии (Phase 45) — рядом с
Telegram Mini App `initData`, не вместо неё (см. src/adapters/api.py::
get_authorized_user). Тот же hand-rolled HMAC-стиль, что уже везде в
проекте (telegram_auth.py, tasker_webhook.py::_verify_secret) — не
тащим itsdangerous/pyjwt ради полутора десятков строк."""

import base64
import hashlib
import hmac
import json
import time

from src.core.config import settings

_SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 дней
SESSION_COOKIE_NAME = "session"


def create_session_token(user_id: int) -> str:
    if not settings.session_secret:
        # Без секрета HMAC считался бы пустым ключом — подделываемо кем
        # угодно, кто просто прочитал код (Phase 58, БАГ безопасности,
        # см. комментарий у Settings.session_secret). session_secret —
        # опциональная фича (веб-вход вне Telegram можно не включать
        # вовсе), но тогда она должна быть выключена целиком, не
        # молчаливо небезопасна.
        raise RuntimeError("SESSION_SECRET не настроен — вход в веб-версию недоступен.")
    payload = json.dumps({"uid": user_id, "exp": int(time.time()) + _SESSION_MAX_AGE_SECONDS})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    signature = hmac.new(
        settings.session_secret.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str) -> int | None:
    """Возвращает user_id при валидной, не протухшей подписи — иначе None.
    Не бросает исключений ни на каком мусорном вводе (кука — недоверенный
    ввод от клиента, тот же принцип, что verify_miniapp_init_data)."""
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
        uid = int(payload["uid"])
        exp = int(payload["exp"])
    except (ValueError, KeyError, TypeError):
        return None

    if time.time() > exp:
        return None
    return uid
