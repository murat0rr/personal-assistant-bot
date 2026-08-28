import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.handlers.f1_task_note import router as f1_router

logger = logging.getLogger(__name__)

dp = Dispatcher()
dp.include_router(f1_router)


@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    if not message.from_user or not is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return
    await message.answer("Привет! Я на связи.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.telegram_bot_token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
