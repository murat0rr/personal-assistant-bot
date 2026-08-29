from aiogram import Bot

from src.core.config import settings

# Отдельный лёгкий инстанс бота для процесса api (только исходящие
# сообщения, без polling) — нужен, чтобы вебхуки (например, гео-напоминания)
# могли сразу написать пользователю, не дожидаясь плановой джобы в bot-процессе.
# Ленивая инициализация — иначе импорт этого модуля в тестах падает на
# валидации формата токена (в тестовом окружении токен фиктивный).
_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.telegram_bot_token)
    return _bot
