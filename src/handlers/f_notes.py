import logging

from aiogram.types import Message

from src.core.config import settings
from src.integrations.notion import create_note

logger = logging.getLogger(__name__)


async def handle_note(message: Message, text: str) -> None:
    if not settings.notion_notes_db_id:
        await message.answer("Notion пока не настроен — база Notes не подключена.")
        return

    try:
        url = await create_note(text)
    except Exception:
        logger.exception("Не удалось сохранить заметку: %r", text)
        await message.answer("Не получилось сохранить заметку, попробуй ещё раз.")
        return

    await message.answer(f"Записал заметку.\n{url}")
