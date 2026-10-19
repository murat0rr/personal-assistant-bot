import time

import pytest

from src.core import login_codes

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_generated_code_verifies_and_returns_user_id():
    code = await login_codes.generate_code(user_id=42)
    assert await login_codes.verify_code(code) == 42


async def test_code_is_one_time_use():
    code = await login_codes.generate_code(user_id=42)
    assert await login_codes.verify_code(code) == 42
    assert await login_codes.verify_code(code) is None


async def test_unknown_code_rejected():
    assert await login_codes.verify_code("0000") is None


async def test_expired_code_rejected():
    code = await login_codes.generate_code(user_id=42)
    key = f"webcode:code:{code}"
    value, _ = login_codes._redis.store[key]
    login_codes._redis.store[key] = (value, time.time() - 1)
    assert await login_codes.verify_code(code) is None


async def test_request_cooldown():
    await login_codes.generate_code(user_id=42)
    assert await login_codes.can_request_code(42) is False


async def test_different_users_have_independent_cooldowns():
    await login_codes.generate_code(user_id=42)
    assert await login_codes.can_request_code(99) is True


async def test_verify_rate_limit_per_ip():
    for _ in range(login_codes._MAX_VERIFY_ATTEMPTS_PER_IP):
        assert await login_codes.can_attempt_verify("1.2.3.4") is True
        await login_codes.record_verify_attempt("1.2.3.4")
    assert await login_codes.can_attempt_verify("1.2.3.4") is False
    # Другой IP не задет чужим лимитом.
    assert await login_codes.can_attempt_verify("5.6.7.8") is True


async def test_verify_attempt_counter_gets_ttl_on_first_call():
    # Регрессия на фикс 2026-10-20 (TECHDEBT.md) — раньше TTL ставился
    # отдельной командой только при new_count == 1 и мог вообще не
    # выполниться, если процесс падал между INCR и EXPIRE; теперь
    # INCR+EXPIRE NX идут одной атомарной транзакцией.
    key = "webcode:verify_attempts:9.9.9.9"
    await login_codes.record_verify_attempt("9.9.9.9")
    _, expire_at = login_codes._redis.store[key]
    assert expire_at is not None


async def test_verify_attempt_counter_self_heals_if_ttl_missing():
    # Симулируем унаследованное от старого бага состояние — счётчик
    # уже существует, но без TTL (раньше это означало "заблокирован
    # навсегда", т.к. new_count больше никогда не равнялось 1).
    key = "webcode:verify_attempts:8.8.8.8"
    login_codes._redis.store[key] = ("5", None)
    await login_codes.record_verify_attempt("8.8.8.8")
    value, expire_at = login_codes._redis.store[key]
    assert value == "6"
    assert expire_at is not None
