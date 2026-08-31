"""Вход в веб-версию через код в чате с ботом (Phase 45, вторая переделка).

Первая версия резолвила Telegram-username через Bot API (`getChat`) —
живая проверка показала, что `getChat("@username")` для обычного
приватного пользователя ненадёжен и часто отвечает "chat not found",
даже если бот с этим человеком уже переписывался (ограничение самого
Bot API, не наша ошибка). Исправлено разворотом инициативы: не сайт
ищет пользователя по имени, а пользователь сам пишет боту команду
/webcode (src/handlers/f_web_login.py) — тогда user_id известен без
всякого резолвинга, напрямую из входящего сообщения. Сайт после этого
спрашивает только сам код, без username вообще.

Хранилище — тот же простой in-memory dict, что и в первой версии (см.
её обоснование: один процесс api, короткоживущий одноразовый код, при
рестарте — просто "запросите код заново")."""

import secrets
import time

_CODE_TTL_SECONDS = 5 * 60
_REQUEST_COOLDOWN_SECONDS = 60
# Раз проверка теперь — прямой lookup по самому коду (см. verify_code),
# а не сравнение "код для этого username" (у которого была своя защита
# от перебора на конкретную запись), у 4 цифр всего 10000 вариантов —
# 5 минут теоретически хватает на подбор скриптом (10000/300с ≈ 33
# попытки/с). Ограничиваем не попытки на код, а попытки С ОДНОГО IP —
# кто угодно может перебирать код собственного запроса сколько угодно
# раз, но не устраивать перебор всего пространства кодов.
_MAX_VERIFY_ATTEMPTS_PER_IP = 20
_VERIFY_WINDOW_SECONDS = 5 * 60

# 4-значный код -> запись. Ключ — сам код (не username/user_id), потому
# что верификация на сайте знает только код.
_PENDING: dict[str, dict] = {}
# user_id -> когда последний раз генерировали код — кулдаун между
# запросами, отдельный индекс, раз основной теперь ключуется кодом.
_LAST_REQUESTED: dict[int, float] = {}
# ip -> список таймстампов попыток верификации за последнее окно.
_VERIFY_ATTEMPTS_BY_IP: dict[str, list[float]] = {}


def can_attempt_verify(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _VERIFY_ATTEMPTS_BY_IP.get(ip, []) if now - t < _VERIFY_WINDOW_SECONDS]
    _VERIFY_ATTEMPTS_BY_IP[ip] = attempts
    return len(attempts) < _MAX_VERIFY_ATTEMPTS_PER_IP


def record_verify_attempt(ip: str) -> None:
    _VERIFY_ATTEMPTS_BY_IP.setdefault(ip, []).append(time.time())


def can_request_code(user_id: int) -> bool:
    last = _LAST_REQUESTED.get(user_id)
    if last is None:
        return True
    return time.time() - last >= _REQUEST_COOLDOWN_SECONDS


def generate_code(user_id: int) -> str:
    code = f"{secrets.randbelow(10000):04d}"
    # Практически невозможно на личном проекте с несколькими
    # пользователями, но раз ключ теперь — сам код, дублирующийся ключ
    # молча стёр бы чужую ожидающую запись — перегенерируем при
    # коллизии, а не полагаемся на "не случится".
    while code in _PENDING:
        code = f"{secrets.randbelow(10000):04d}"
    _PENDING[code] = {
        "user_id": user_id,
        "expires_at": time.time() + _CODE_TTL_SECONDS,
    }
    _LAST_REQUESTED[user_id] = time.time()
    return code


def verify_code(code: str) -> int | None:
    """Возвращает user_id при совпадении кода — иначе None. Код
    одноразовый (удаляется сразу после успеха ИЛИ по истечении TTL —
    в обоих случаях запись больше не годится). Защита от перебора всего
    пространства кодов — не здесь, а по IP на уровне вызывающего кода
    (can_attempt_verify/record_verify_attempt выше), поскольку прямой
    lookup по коду не даёт естественного места для "попыток на одну
    запись", как было в первой версии (там ключом был username)."""
    entry = _PENDING.get(code)
    if entry is None:
        return None
    if time.time() > entry["expires_at"]:
        del _PENDING[code]
        return None
    del _PENDING[code]
    return entry["user_id"]
