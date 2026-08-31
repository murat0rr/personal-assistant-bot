import time

from src.core import login_codes


def _reset(username: str) -> None:
    login_codes._PENDING.pop(username, None)


def test_generated_code_verifies_and_returns_user_id():
    _reset("alice")
    code = login_codes.generate_code("alice", user_id=42)
    assert login_codes.verify_code("alice", code) == 42


def test_code_is_one_time_use():
    _reset("alice")
    code = login_codes.generate_code("alice", user_id=42)
    assert login_codes.verify_code("alice", code) == 42
    assert login_codes.verify_code("alice", code) is None


def test_wrong_code_rejected():
    _reset("alice")
    login_codes.generate_code("alice", user_id=42)
    assert login_codes.verify_code("alice", "0000") is None


def test_unknown_username_rejected():
    _reset("nobody")
    assert login_codes.verify_code("nobody", "1234") is None


def test_expired_code_rejected():
    _reset("alice")
    code = login_codes.generate_code("alice", user_id=42)
    login_codes._PENDING["alice"]["expires_at"] = time.time() - 1
    assert login_codes.verify_code("alice", code) is None


def test_too_many_attempts_invalidates_code():
    _reset("alice")
    code = login_codes.generate_code("alice", user_id=42)
    for _ in range(login_codes._MAX_VERIFY_ATTEMPTS):
        assert login_codes.verify_code("alice", "0000") is None
    # Даже правильный код после исчерпанных попыток больше не годится —
    # запись уже сгорела.
    assert login_codes.verify_code("alice", code) is None


def test_request_cooldown():
    _reset("alice")
    login_codes.generate_code("alice", user_id=42)
    assert login_codes.can_request_code("alice") is False
    login_codes._PENDING["alice"]["requested_at"] = time.time() - 61
    assert login_codes.can_request_code("alice") is True


def test_normalize_username_strips_at_and_lowercases():
    assert login_codes.normalize_username("@Alice") == "alice"
    assert login_codes.normalize_username("  Bob  ") == "bob"
