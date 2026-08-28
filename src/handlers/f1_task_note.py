import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import Message

from src.core.config import settings
from src.integrations.claude_client import extract_task_fields
from src.integrations.notion import create_task

logger = logging.getLogger(__name__)


async def handle_task_note(message: Message, text: str) -> None:
    if not settings.notion_tasks_db_id:
        await message.answer("Notion пока не настроен — база Tasks не подключена.")
        return

    try:
        today = datetime.now(ZoneInfo(settings.timezone)).date()
        fields = await extract_task_fields(text, today)
        url = await create_task(fields.title, fields.due_date, fields.priority)
    except Exception:
        logger.exception("Не удалось создать задачу из сообщения: %r", text)
        await message.answer("Не получилось создать задачу, попробуй ещё раз.")
        return

    due_str = fields.due_date.strftime("%d.%m.%Y") if fields.due_date else "без срока"
    await message.answer(
        f"Готово: «{fields.title}» ({due_str}, приоритет: {fields.priority})\n{url}"
    )
