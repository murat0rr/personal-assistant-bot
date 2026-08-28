from aiogram import Bot

from src.core.config import settings

_bot = Bot(token=settings.telegram_bot_token)


async def notify_owner(text: str) -> None:
    """Отправить сообщение владельцу бота из процесса api (не через Dispatcher)."""
    await _bot.send_message(chat_id=settings.telegram_user_id, text=text)
