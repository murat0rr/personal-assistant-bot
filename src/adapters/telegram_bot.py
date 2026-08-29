import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.message_tracking import attach_message_tracking, track_incoming
from src.core.notion_sync import sync_tasks_from_notion
from src.core.orchestrator import router as orchestrator_router
from src.handlers.f4_diary import router as diary_router
from src.scheduler.jobs import setup_scheduler

logger = logging.getLogger(__name__)

# RedisStorage переживает рестарт контейнера (важно — вечерний опрос может
# идти как раз в момент деплоя); без REDIS_URL откатываемся на память.
storage = RedisStorage.from_url(settings.redis_url) if settings.redis_url else MemoryStorage()
dp = Dispatcher(storage=storage)
dp.message.outer_middleware(track_incoming)

# diary_router — раньше orchestrator_router: пока активен FSM-опрос,
# текстовые ответы должны ловиться по state, а не падать в общий capture.
dp.include_router(diary_router)
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
    attach_message_tracking(bot)

    if settings.notion_tasks_db_id:
        # Разовый синк сразу при старте (без уведомлений — иначе каждый
        # рестарт контейнера спамил бы про "изменившиеся" статусы), плюс
        # плановые джобы: дневной синк, утренняя сводка, вечерний дневник.
        await sync_tasks_from_notion(notify_on_change=False)
        scheduler = setup_scheduler(bot, dp.storage)
        scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
