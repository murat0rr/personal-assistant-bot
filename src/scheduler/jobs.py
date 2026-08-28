import logging

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import settings
from src.core.notion_sync import sync_tasks_from_notion
from src.handlers.f4_diary import DiaryStates, ask_question
from src.handlers.f5_morning_digest import build_morning_digest

logger = logging.getLogger(__name__)


async def _daily_sync() -> None:
    logger.info("Запуск дневного синка задач из Notion")
    await sync_tasks_from_notion(notify_on_change=True)


async def _morning_digest(bot: Bot) -> None:
    logger.info("Формирую утреннюю сводку")
    await sync_tasks_from_notion(notify_on_change=False)
    text = await build_morning_digest()
    await bot.send_message(chat_id=settings.telegram_user_id, text=text)


async def _evening_diary(bot: Bot, storage: BaseStorage) -> None:
    logger.info("Запускаю вечерний опрос дневника")
    key = StorageKey(
        bot_id=bot.id,
        chat_id=settings.telegram_user_id,
        user_id=settings.telegram_user_id,
    )
    state = FSMContext(storage=storage, key=key)
    await state.set_data({})
    await ask_question(bot, state, DiaryStates.physical)


def setup_scheduler(bot: Bot, storage: BaseStorage) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(_daily_sync, CronTrigger(hour=3, minute=0))
    scheduler.add_job(_morning_digest, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_evening_diary, CronTrigger(hour=21, minute=0), args=[bot, storage])
    return scheduler
