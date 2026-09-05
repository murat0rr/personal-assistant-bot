import logging
from datetime import datetime

from aiogram.types import Message

from src.core.db import async_session
from src.core.user_location import user_today
from src.integrations.claude_client import extract_tasks_fields
from src.models.task import Task

logger = logging.getLogger(__name__)


async def handle_task_note(message: Message, text: str) -> None:
    if not message.from_user:
        return
    try:
        today = await user_today(message.from_user.id)
        # Одно сообщение может называть несколько задач сразу (Phase 49) —
        # extract_tasks_fields всегда возвращает список, даже для обычного
        # однозадачного текста (тогда просто из одного элемента).
        tasks_fields = await extract_tasks_fields(text, today)

        async with async_session() as session:
            for fields in tasks_fields:
                task = Task(
                    user_id=message.from_user.id,
                    title=fields.title,
                    # due_date в БД — timestamp; голосовая/текстовая задача
                    # времени не задаёт, поэтому дата целиком идёт на полночь
                    # (конвенция "время не указано", см. handlers/miniapp_tasks.py).
                    due_date=datetime.combine(fields.due_date, datetime.min.time())
                    if fields.due_date
                    else None,
                    priority=fields.priority,
                    sphere=fields.sphere,
                    description=fields.description,
                    source="F1",
                )
                session.add(task)
            # Один commit на все задачи сообщения — либо все создались,
            # либо (при сбое где-то выше) ни одной, не половина.
            await session.commit()
    except Exception:
        logger.exception("Не удалось создать задачу(-и) из сообщения: %r", text)
        await message.answer("Не получилось создать задачу, попробуй ещё раз.")
        return

    def _line(fields) -> str:
        due_str = fields.due_date.strftime("%d.%m.%Y") if fields.due_date else "без срока"
        return f"«{fields.title}» ({due_str}, приоритет: {fields.priority})"

    if len(tasks_fields) == 1:
        await message.answer(f"Готово: {_line(tasks_fields[0])}")
    else:
        lines = "\n".join(f"— {_line(f)}" for f in tasks_fields)
        await message.answer(f"Готово, создал {len(tasks_fields)} задачи:\n{lines}")
