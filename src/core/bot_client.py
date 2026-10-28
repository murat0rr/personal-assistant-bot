from aiogram import Bot
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from src.core.config import settings

# Отдельный лёгкий инстанс бота для процесса api (только исходящие
# сообщения, без polling) — нужен, чтобы вебхуки (например, гео-напоминания)
# могли сразу написать пользователю, не дожидаясь плановой джобы в bot-процессе.
# Ленивая инициализация — иначе импорт этого модуля в тестах падает на
# валидации формата токена (в тестовом окружении токен фиктивный).
_bot: Bot | None = None
_storage: BaseStorage | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.telegram_bot_token)
    return _bot


def get_storage() -> BaseStorage:
    """FSM-хранилище для процесса api (фидбек 2026-10-24, похвала за
    закрытый день) — та же RedisStorage, что строит bot-процесс в
    telegram_bot.py (ключи в Redis общие, оба процесса читают/пишут
    один FSMContext по одному StorageKey), просто свой инстанс
    клиента, а не общая память — иначе `send_morning_advice`/кнопки
    "Добавить"/"Не сегодня" из этого вызова не нашли бы от api-процесса
    то, что положил bot-процесс, и наоборот. MemoryStorage-фоллбек без
    REDIS_URL бесполезен между процессами, но не должен ронять импорт
    модуля в тестах (как и у _bot выше)."""
    global _storage
    if _storage is None:
        _storage = (
            RedisStorage.from_url(settings.redis_url) if settings.redis_url else MemoryStorage()
        )
    return _storage
