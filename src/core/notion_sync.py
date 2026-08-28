import logging

from src.core.db import async_session
from src.integrations import notion
from src.integrations.telegram_notify import notify_owner
from src.models.task import Task

logger = logging.getLogger(__name__)


async def sync_tasks_from_notion(*, notify_on_change: bool) -> int:
    """Подтянуть все задачи из Notion и обновить кэш в Postgres.

    Используется и плановым джобом (раз в день), и по требованию — при
    открытии Mini App. Уведомление в Telegram шлётся только когда статус
    реально изменился относительно того, что уже было в Postgres — так
    открытие Mini App (notify_on_change=False) не спамит, а плановый синк
    (notify_on_change=True) сообщает только о настоящих изменениях.
    """
    tasks = await notion.list_tasks()

    async with async_session() as session:
        for parsed in tasks:
            existing = await session.get(Task, parsed["notion_page_id"])
            status_changed = existing is not None and existing.status != parsed["status"]

            if existing is None:
                existing = Task(notion_page_id=parsed["notion_page_id"])
                session.add(existing)
            existing.title = parsed["title"]
            existing.due_date = parsed["due_date"]
            existing.priority = parsed["priority"]
            existing.status = parsed["status"]
            existing.source = parsed["source"]

            if notify_on_change and status_changed:
                await notify_owner(f"Статус «{parsed['title']}» изменился: {parsed['status']}")

        await session.commit()

    logger.info("Синхронизировано задач из Notion: %s", len(tasks))
    return len(tasks)
