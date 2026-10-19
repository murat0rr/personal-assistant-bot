"""Вход в веб-версию через код в чате с ботом (Phase 45, третья
переделка). Код рождается в процессе `bot` (/webcode,
src/handlers/f_web_login.py), а проверяется в процессе `api`
(src/adapters/web_auth.py) — это ДВА РАЗНЫХ контейнера/процесса, у
каждого своя память. Первая реализация этого модуля держала код в
обычном Python-словаре — работала бы, будь это один процесс, но между
`bot` и `api` общей памяти нет вообще: код, сгенерированный в `bot`,
был просто невидим для `api`, "неверный код" даже при мгновенном вводе.
Найдено сразу на живой проверке. Правильное общее хранилище между
процессами в этом стеке уже есть — Redis (settings.redis_url), им и
пользуемся вместо словаря."""

import secrets

import redis.asyncio as redis

from src.core.config import settings

_CODE_TTL_SECONDS = 5 * 60
_REQUEST_COOLDOWN_SECONDS = 60
# См. docstring верхнего уровня прошлых версий: раз проверка — прямой
# lookup по самому коду, а не сравнение "код для этого X", у 4 цифр
# всего 10000 вариантов — ограничиваем попытки верификации по IP,
# не по конкретному коду.
_MAX_VERIFY_ATTEMPTS_PER_IP = 20
_VERIFY_WINDOW_SECONDS = 5 * 60

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def can_request_code(user_id: int) -> bool:
    exists = await _get_redis().exists(f"webcode:cooldown:{user_id}")
    return not exists


async def generate_code(user_id: int) -> str:
    r = _get_redis()
    code = f"{secrets.randbelow(10000):04d}"
    # Практически невозможно на личном проекте с несколькими
    # пользователями, но раз ключ — сам код, коллизия молча стёрла бы
    # чужую ожидающую запись — перегенерируем, а не полагаемся на "не
    # случится".
    while await r.exists(f"webcode:code:{code}"):
        code = f"{secrets.randbelow(10000):04d}"
    await r.set(f"webcode:code:{code}", str(user_id), ex=_CODE_TTL_SECONDS)
    await r.set(f"webcode:cooldown:{user_id}", "1", ex=_REQUEST_COOLDOWN_SECONDS)
    return code


async def verify_code(code: str) -> int | None:
    """Возвращает user_id при совпадении кода — иначе None. Код
    одноразовый: удаляется сразу после успешного чтения (TTL в Redis
    сам убирает протухшие записи, отдельная проверка не нужна).

    GETDEL (не раздельные get+delete, см. TECHDEBT.md) — атомарная
    команда Redis, читает и сразу удаляет ключ одной операцией. Раньше
    между get и delete была точка ожидания: два параллельных
    POST /auth/verify с одним кодом могли оба прочитать значение до
    того, как первый успеет удалить — код, объявленный одноразовым,
    аутентифицировал двоих."""
    value = await _get_redis().getdel(f"webcode:code:{code}")
    if value is None:
        return None
    return int(value)


async def can_attempt_verify(ip: str) -> bool:
    count = await _get_redis().get(f"webcode:verify_attempts:{ip}")
    return count is None or int(count) < _MAX_VERIFY_ATTEMPTS_PER_IP


async def record_verify_attempt(ip: str) -> None:
    """INCR и EXPIRE в одной атомарной транзакции (Redis MULTI/EXEC —
    redis-py пайплайн транзакционный по умолчанию), не раздельными
    вызовами (см. TECHDEBT.md). Раньше TTL ставился отдельной командой
    только при new_count == 1 — если процесс падал/рвал соединение
    между INCR и EXPIRE, ключ оставался в Redis без TTL НАВСЕГДА
    (условие "new_count == 1" больше никогда не истинно), и IP был
    заблокирован безвозвратно после 20 попыток.

    EXPIRE ... NX (ставит TTL, только если его ещё нет) вместо условия
    на new_count — тот же эффект (TTL ставится ровно один раз, на
    первой попытке), но в одной атомарной операции с INCR, и
    самовосстанавливается: если ключ каким-то образом уже остался без
    TTL (старый баг/ручное вмешательство), ближайший же вызов поставит
    TTL сам, а не продлит поломку."""
    r = _get_redis()
    key = f"webcode:verify_attempts:{ip}"
    async with r.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, _VERIFY_WINDOW_SECONDS, nx=True)
        await pipe.execute()
