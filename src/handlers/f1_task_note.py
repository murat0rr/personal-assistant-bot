import logging
from datetime import datetime

from aiogram.types import Message

from src.core.db import async_session
from src.core.user_location import user_today
from src.integrations.claude_client import extract_task_fields
from src.models.task import Task

logger = logging.getLogger(__name__)


async def handle_task_note(message: Message, text: str) -> None:
    if not message.from_user:
        return
    try:
        today = await user_today(message.from_user.id)
        fields = await extract_task_fields(text, today)

        async with async_session() as session:
            task = Task(
                user_id=message.from_user.id,
                title=fields.title,
                # due_date в БД — timestamp; голосовая/текстовая задача времени
                # не задаёт, поэтому дата целиком идёт на полночь (конвенция
                # "время не указано", см. handlers/miniapp_tasks.py).
                due_date=datetime.combine(fields.due_date, datetime.min.time())
                if fields.due_date
                else None,
                priority=fields.priority,
                source="F1",
            )
            session.add(task)
            await session.commit()
    except Exception:
        logger.exception("Не удалось создать задачу из сообщения: %r", text)
        await message.answer("Не получилось создать задачу, попробуй ещё раз.")
        return

    due_str = fields.due_date.strftime("%d.%m.%Y") if fields.due_date else "без срока"
    await message.answer(f"Готово: «{fields.title}» ({due_str}, приоритет: {fields.priority})")
