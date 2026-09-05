"""OAuth `state` для подключения Google Calendar (Phase 64) — тот же
приём, что уже есть у входа в веб-версию (см. src/core/login_codes.py):
код рождается в процессе `bot` (/google_calendar,
src/handlers/f_google_calendar.py), а проверяется в процессе `api`
(src/adapters/google_oauth.py) — разные контейнеры без общей памяти,
общее хранилище — Redis (settings.redis_url)."""

import secrets

import redis.asyncio as redis

from src.core.config import settings

_STATE_TTL_SECONDS = 10 * 60

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def generate_state(user_id: int) -> str:
    token = secrets.token_urlsafe(24)
    await _get_redis().set(f"google_oauth_state:{token}", str(user_id), ex=_STATE_TTL_SECONDS)
    return token


async def consume_state(token: str) -> int | None:
    """Возвращает user_id при совпадении токена — иначе None. Одноразовый:
    удаляется сразу после чтения (TTL в Redis сам убирает протухшие
    записи)."""
    r = _get_redis()
    key = f"google_oauth_state:{token}"
    value = await r.get(key)
    if value is None:
        return None
    await r.delete(key)
    return int(value)
