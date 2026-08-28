import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.integrations.claude_client import extract_task_fields
from src.integrations.notion import create_task
from src.integrations.stt import stt

logger = logging.getLogger(__name__)

router = Router()

# voice-сообщение, либо текст, не являющийся командой (не начинается с "/")
_TASK_NOTE_FILTER = F.voice | (F.text & ~F.text.startswith("/"))


@router.message(_TASK_NOTE_FILTER)
async def handle_task_note(message: Message) -> None:
    if not message.from_user or not is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    if not settings.notion_tasks_db_id:
        await message.answer("Notion пока не настроен — база Tasks не подключена.")
        return

    if message.voice:
        assert message.bot is not None
        file = await message.bot.get_file(message.voice.file_id)
        assert file.file_path is not None
        buf = await message.bot.download_file(file.file_path)
        assert buf is not None
        text = await stt.transcribe(buf.read(), "voice.ogg")
    else:
        assert message.text is not None
        text = message.text

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
