import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.notion_sync import sync_tasks_from_notion
from src.core.orchestrator import router as orchestrator_router
from src.scheduler.jobs import setup_scheduler

logger = logging.getLogger(__name__)

dp = Dispatcher()
dp.include_router(orchestrator_router)


@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    if not message.from_user or not is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return
    await message.answer("Привет! Я на связи.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.telegram_bot_token)

    if settings.notion_tasks_db_id:
        # Разовый синк сразу при старте (без уведомлений — иначе каждый
        # рестарт контейнера спамил бы про "изменившиеся" статусы), плюс
        # плановая ежедневная джоба с уведомлениями.
        await sync_tasks_from_notion(notify_on_change=False)
        scheduler = setup_scheduler()
        scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
