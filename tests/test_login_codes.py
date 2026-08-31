import time

from src.core import login_codes


def _reset() -> None:
    login_codes._PENDING.clear()
    login_codes._LAST_REQUESTED.clear()
    login_codes._VERIFY_ATTEMPTS_BY_IP.clear()


def test_generated_code_verifies_and_returns_user_id():
    _reset()
    code = login_codes.generate_code(user_id=42)
    assert login_codes.verify_code(code) == 42


def test_code_is_one_time_use():
    _reset()
    code = login_codes.generate_code(user_id=42)
    assert login_codes.verify_code(code) == 42
    assert login_codes.verify_code(code) is None


def test_unknown_code_rejected():
    _reset()
    assert login_codes.verify_code("0000") is None


def test_expired_code_rejected():
    _reset()
    code = login_codes.generate_code(user_id=42)
    login_codes._PENDING[code]["expires_at"] = time.time() - 1
    assert login_codes.verify_code(code) is None


def test_request_cooldown():
    _reset()
    login_codes.generate_code(user_id=42)
    assert login_codes.can_request_code(42) is False
    login_codes._LAST_REQUESTED[42] = time.time() - 61
    assert login_codes.can_request_code(42) is True


def test_different_users_have_independent_cooldowns():
    _reset()
    login_codes.generate_code(user_id=42)
    assert login_codes.can_request_code(99) is True


def test_verify_rate_limit_per_ip():
    _reset()
    for _ in range(login_codes._MAX_VERIFY_ATTEMPTS_PER_IP):
        assert login_codes.can_attempt_verify("1.2.3.4") is True
        login_codes.record_verify_attempt("1.2.3.4")
    assert login_codes.can_attempt_verify("1.2.3.4") is False
    # Другой IP не задет чужим лимитом.
    assert login_codes.can_attempt_verify("5.6.7.8") is True


def test_verify_rate_limit_window_expires():
    _reset()
    login_codes._VERIFY_ATTEMPTS_BY_IP["1.2.3.4"] = [
        time.time() - login_codes._VERIFY_WINDOW_SECONDS - 1
    ] * login_codes._MAX_VERIFY_ATTEMPTS_PER_IP
    assert login_codes.can_attempt_verify("1.2.3.4") is True
