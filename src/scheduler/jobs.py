import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import settings
from src.core.notion_sync import sync_tasks_from_notion

logger = logging.getLogger(__name__)


async def _daily_sync() -> None:
    logger.info("Запуск дневного синка задач из Notion")
    await sync_tasks_from_notion(notify_on_change=True)


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(_daily_sync, CronTrigger(hour=3, minute=0))
    return scheduler
