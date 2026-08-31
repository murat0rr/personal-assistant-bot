import os
import time

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_USER_ID", "12345")


class FakeRedis:
    """Реализует ровно тот подмножество команд Redis, что использует
    src/core/login_codes.py (Phase 45 — вход в веб-версию через код в
    чате с ботом, хранилище общее между процессами bot/api). Не тащим
    fakeredis как отдельную зависимость ради шести методов."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, float | None]] = {}

    def _expired(self, key: str) -> bool:
        if key not in self.store:
            return True
        _, expire_at = self.store[key]
        if expire_at is not None and time.time() > expire_at:
            del self.store[key]
            return True
        return False

    async def exists(self, key: str) -> int:
        return 0 if self._expired(key) else 1

    async def get(self, key: str) -> str | None:
        return None if self._expired(key) else self.store[key][0]

    async def set(self, key: str, value: object, ex: int | None = None) -> bool:
        expire_at = time.time() + ex if ex is not None else None
        self.store[key] = (str(value), expire_at)
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                count += 1
        return count

    async def incr(self, key: str) -> int:
        current = 0 if self._expired(key) else int(self.store[key][0])
        new_value = current + 1
        expire_at = None if key not in self.store else self.store[key][1]
        self.store[key] = (str(new_value), expire_at)
        return new_value

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self.store:
            value, _ = self.store[key]
            self.store[key] = (value, time.time() + seconds)
        return True


@pytest.fixture(autouse=True)
def fake_redis_for_login_codes():
    """Подменяет модульный singleton-клиент в login_codes.py на
    FakeRedis для каждого теста — иначе _get_redis() попытался бы
    подключиться к реальному REDIS_URL (в тестовом окружении пустой)."""
    from src.core import login_codes

    login_codes._redis = FakeRedis()
    yield
    login_codes._redis = None
