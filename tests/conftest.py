import os
import time

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_USER_ID", "12345")
# Обязательное поле без дефолта в коде с Phase 58 (см. src/core/config.py)
# — тесты не должны зависеть от того, что .env локально уже его задаёт.
os.environ.setdefault("BOT_ACCESS_PASSWORD", "test-password")
# session_secret остаётся опциональным полем (веб-вход можно не включать),
# но test_api.py::test_login_page_renders_code_form и соседние тесты
# проверяют именно ВКЛЮЧЁННЫЙ /auth/login — без этого с Phase 58 (см.
# web_auth.py — пустой секрет теперь отвечает "не настроено", раньше
# молча подписывал HMAC пустым ключом) они упирались бы в "не настроено".
# tests/test_web_session.py по-прежнему явно переопределяет значение
# в каждом тесте, этому дефолту не мешает.
os.environ.setdefault("SESSION_SECRET", "test-session-secret")


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

    async def expire(
        self,
        key: str,
        seconds: int,
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> bool:
        """nx поддержан (единственный флаг, которым реально пользуется
        login_codes.py::record_verify_attempt — атомарная фикс-правка
        2026-10-20, см. TECHDEBT.md) — xx/gt/lt не реализованы, никто
        в проекте их не зовёт."""
        if key not in self.store:
            return False
        value, current_expire_at = self.store[key]
        if nx and current_expire_at is not None:
            return False
        self.store[key] = (value, time.time() + seconds)
        return True

    async def getdel(self, key: str) -> str | None:
        """Атомарный get+delete (login_codes.py::verify_code, фикс
        2026-10-20) — в тестовом дабле атомарность бесплатна, нет
        настоящей конкурентности внутри одного event loop без await
        между чтением и удалением."""
        if self._expired(key):
            return None
        value, _ = self.store[key]
        del self.store[key]
        return value

    def pipeline(self, transaction: bool = True) -> "_FakePipeline":
        return _FakePipeline(self)


class _FakePipeline:
    """Минимальная эмуляция транзакционного пайплайна redis-py —
    команды копятся без await (как и в настоящем клиенте), выполняются
    по порядку при execute(). Поддержаны только incr/expire — всё, что
    сейчас реально собирают в пайплайн (login_codes.py::record_verify_attempt)."""

    def __init__(self, redis: "FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple, dict]] = []

    def incr(self, key: str) -> "_FakePipeline":
        self._ops.append(("incr", (key,), {}))
        return self

    def expire(self, key: str, seconds: int, **kwargs: object) -> "_FakePipeline":
        self._ops.append(("expire", (key, seconds), kwargs))
        return self

    async def execute(self) -> list:
        results = [
            await getattr(self._redis, name)(*args, **kwargs) for name, args, kwargs in self._ops
        ]
        self._ops = []
        return results

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_redis_for_login_codes():
    """Подменяет модульный singleton-клиент в login_codes.py и
    tasks_cache.py на FakeRedis для каждого теста — иначе _get_redis()
    попытался бы подключиться к реальному REDIS_URL (в тестовом
    окружении пустой). Общая FakeRedis на оба модуля не нужна — у
    каждого свой независимый store, они не пересекаются по ключам."""
    from src.core import login_codes, tasks_cache

    login_codes._redis = FakeRedis()
    tasks_cache._redis = FakeRedis()
    yield
    login_codes._redis = None
    tasks_cache._redis = None
