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
