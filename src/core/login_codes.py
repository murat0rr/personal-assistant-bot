"""Вход в веб-версию через код в чате с ботом (Phase 45, переделано —
исходный вариант через Telegram Login Widget упёрся в недоставку кода
подтверждения самим Telegram, вне нашего контроля). Идея: раз человек
уже писал боту (иначе он не в authorized_users), бот может просто
прислать код сам, своим обычным sendMessage — та же доставка, что
работает для дайджестов/напоминаний весь проект.

Хранилище — простой in-memory dict, без Redis: код живёт 5 минут, один
процесс api (без --workers), рестарт при деплое означает лишь "запросите
код заново" — не критично для одноразового короткого кода. Если станет
проблемой (несколько воркеров api) — переезд на Redis тривиален, он уже
в стеке."""

import secrets
import time

_CODE_TTL_SECONDS = 5 * 60
_REQUEST_COOLDOWN_SECONDS = 60
_MAX_VERIFY_ATTEMPTS = 5

# username (нормализован — без "@", в нижнем регистре) -> запись.
_PENDING: dict[str, dict] = {}


def normalize_username(username: str) -> str:
    return username.strip().lstrip("@").lower()


def can_request_code(username: str) -> bool:
    """Кулдаун между запросами кода на один и тот же username — не даёт
    засыпать чужой чат с ботом кодами при повторных кликах/атаке."""
    entry = _PENDING.get(username)
    if entry is None:
        return True
    return time.time() - entry["requested_at"] >= _REQUEST_COOLDOWN_SECONDS


def generate_code(username: str, user_id: int) -> str:
    code = f"{secrets.randbelow(10000):04d}"
    _PENDING[username] = {
        "user_id": user_id,
        "code": code,
        "expires_at": time.time() + _CODE_TTL_SECONDS,
        "requested_at": time.time(),
        "attempts": 0,
    }
    return code


def verify_code(username: str, code: str) -> int | None:
    """Возвращает user_id при совпадении кода — иначе None. Код
    одноразовый (удаляется сразу после успеха) и protected от перебора
    (_MAX_VERIFY_ATTEMPTS неверных попыток — запись сгорает, нужен новый
    код)."""
    entry = _PENDING.get(username)
    if entry is None:
        return None
    if time.time() > entry["expires_at"]:
        del _PENDING[username]
        return None
    if entry["attempts"] >= _MAX_VERIFY_ATTEMPTS:
        del _PENDING[username]
        return None
    if not secrets.compare_digest(entry["code"], code.strip()):
        entry["attempts"] += 1
        return None
    del _PENDING[username]
    return entry["user_id"]
