import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session
from src.core.notion_sync import sync_tasks_from_notion
from src.handlers.f4_diary import DiaryStates, ask_question
from src.handlers.f5_morning_digest import build_morning_digest
from src.handlers.f9_finance import FINANCE_GUIDE
from src.handlers.f11_weekly_review import build_weekly_review
from src.handlers.f_reminders import check_reminders
from src.integrations.notion import list_habits
from src.models.chat_message import ChatMessage
from src.models.screen_time import ScreenTime

logger = logging.getLogger(__name__)


async def _daily_sync() -> None:
    logger.info("Запуск дневного синка задач из Notion")
    await sync_tasks_from_notion(notify_on_change=True)


async def _morning_digest(bot: Bot) -> None:
    logger.info("Формирую утреннюю сводку")
    await sync_tasks_from_notion(notify_on_change=False)
    text = await build_morning_digest()
    await bot.send_message(chat_id=settings.telegram_user_id, text=text)


async def _reminders_job(bot: Bot) -> None:
    logger.info("Проверяю напоминания")
    await check_reminders(bot)


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


async def _cleanup_old_messages(bot: Bot) -> None:
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()

    async with async_session() as session:
        result = await session.execute(select(ChatMessage))
        old_messages = [
            row for row in result.scalars().all() if row.sent_at.astimezone(tz).date() < today
        ]

        for row in old_messages:
            try:
                await bot.delete_message(
                    chat_id=settings.telegram_user_id, message_id=row.message_id
                )
            except TelegramBadRequest:
                # уже удалено вручную, старше 48ч и т.п. — не критично
                pass
            await session.delete(row)

        await session.commit()

    logger.info("Автоочистка чата: удалено сообщений %s", len(old_messages))


async def _finance_reminder_job(bot: Bot) -> None:
    logger.info("Напоминаю про выписку за месяц")
    await bot.send_message(chat_id=settings.telegram_user_id, text=FINANCE_GUIDE)


async def _screen_time_digest(bot: Bot) -> None:
    tz = ZoneInfo(settings.timezone)
    yesterday = (datetime.now(tz) - timedelta(days=1)).date()

    async with async_session() as session:
        entry = await session.get(ScreenTime, yesterday)

    if entry is None:
        logger.info("Экранное время за %s не пришло — пропускаю сводку", yesterday)
        return

    hours, minutes = divmod(entry.total_minutes, 60)
    await bot.send_message(
        chat_id=settings.telegram_user_id,
        text=f"📱 Экранное время вчера: {hours}ч {minutes}м",
    )


async def _weekly_review(bot: Bot) -> None:
    logger.info("Собираю итоги недели")
    text = await build_weekly_review()
    await bot.send_message(chat_id=settings.telegram_user_id, text=text)


async def _habit_reminders(bot: Bot) -> None:
    if not settings.notion_habits_db_id:
        return
    logger.info("Проверяю несделанные привычки")
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    habits = await list_habits()
    missed = [h for h in habits if h["target_frequency"] == "daily" and h["last_checked"] != today]
    if not missed:
        return
    names = "\n".join(f"— {h['name']}" for h in missed)
    await bot.send_message(
        chat_id=settings.telegram_user_id,
        text=f"⏰ Не забудь отметить привычки за сегодня:\n{names}",
    )


def setup_scheduler(bot: Bot, storage: BaseStorage) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(_daily_sync, CronTrigger(hour=3, minute=0))
    scheduler.add_job(_morning_digest, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_reminders_job, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_screen_time_digest, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_finance_reminder_job, CronTrigger(day=1, hour=8, minute=0), args=[bot])
    scheduler.add_job(_weekly_review, CronTrigger(day_of_week="sun", hour=19, minute=0), args=[bot])
    scheduler.add_job(_habit_reminders, CronTrigger(hour=20, minute=0), args=[bot])
    scheduler.add_job(_evening_diary, CronTrigger(hour=21, minute=0), args=[bot, storage])
    scheduler.add_job(_cleanup_old_messages, CronTrigger(hour=0, minute=5), args=[bot])
    return scheduler
