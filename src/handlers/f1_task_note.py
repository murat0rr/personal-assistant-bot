import logging
from datetime import datetime

from aiogram.types import Message

from src.core.db import async_session
from src.core.tasks_cache import invalidate_tasks_cache
from src.core.user_location import user_today
from src.handlers.f_set_day_task import refresh_day_task_message
from src.integrations.claude_client import TaskFields, extract_tasks_fields
from src.models.task import Task

logger = logging.getLogger(__name__)

# Приоритет по конвенции api.py::_DEFAULT_PRIORITY — core/handlers не
# импортируют adapters, своя копия той же строки (тот же приём, что у
# core/chat_watch.py::_DEFAULT_PRIORITY).
_DEFAULT_PRIORITY = "средний"


def _fallback_task_fields(text: str) -> TaskFields:
    """Табличный фолбек без ИИ (фидбек, 2026-10-18) — когда
    extract_tasks_fields падает (прокси CLAUDE_BASE_URL недоступен/
    отбивает ошибку, см. TECHDEBT.md), весь текст целиком становится
    заголовком задачи, без срока/сферы/описания — тот же "тупой" путь,
    что уже существует в adapters/api.py::create_task_endpoint (Mini
    App создаёт задачи без ИИ в синхронном пути, описание — опционально
    фоном). Лучше неидеальная задача, чем молчание."""
    return TaskFields(title=text.strip() or "Задача", priority=_DEFAULT_PRIORITY)


async def handle_task_note(message: Message, text: str) -> None:
    if not message.from_user:
        return
    today = await user_today(message.from_user.id)

    fallback_used = False
    try:
        # Одно сообщение может называть несколько задач сразу (Phase 49) —
        # extract_tasks_fields всегда возвращает список, даже для обычного
        # однозадачного текста (тогда просто из одного элемента).
        tasks_fields = await extract_tasks_fields(text, today)
    except Exception:
        logger.exception("ИИ не разобрал сообщение — создаю задачу без деталей (фолбек): %r", text)
        tasks_fields = [_fallback_task_fields(text)]
        fallback_used = True

    try:
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
                    source="F1_fallback" if fallback_used else "F1",
                )
                session.add(task)
            # Один commit на все задачи сообщения — либо все создались,
            # либо (при сбое где-то выше) ни одной, не половина.
            await session.commit()
        await invalidate_tasks_cache(message.from_user.id)
    except Exception:
        # Сбой здесь — уже не про ИИ (тот случай обработан выше), а про
        # саму БД — фолбеком не лечится, честно сообщаем об ошибке.
        logger.exception("Не удалось сохранить задачу(-и) в БД: %r", text)
        await message.answer("Не получилось создать задачу, попробуй ещё раз.")
        return

    # Живое обновление /day_tasks (Phase 80, фидбек живой проверки) —
    # если новая задача попала на сегодня, а у пользователя уже открыто
    # это сообщение, оно должно увидеть её сразу, не только по
    # следующему тапу/повторной команде. Не должно ронять уже успешное
    # создание задачи, если вдруг сломается — тихо логируется внутри.
    try:
        await refresh_day_task_message(message.bot, message.from_user.id)
    except Exception:
        logger.exception("Не удалось обновить /day_tasks после создания задачи")

    if fallback_used:
        await message.answer(
            f"ИИ сейчас недоступен — сохранил как есть: «{tasks_fields[0].title}» "
            "(без срока, приоритет: средний). Поправь вручную, если нужно."
        )
        return

    def _line(fields) -> str:
        due_str = fields.due_date.strftime("%d.%m.%Y") if fields.due_date else "без срока"
        return f"«{fields.title}» ({due_str}, приоритет: {fields.priority})"

    if len(tasks_fields) == 1:
        await message.answer(f"Готово: {_line(tasks_fields[0])}")
    else:
        lines = "\n".join(f"— {_line(f)}" for f in tasks_fields)
        await message.answer(f"Готово, создал {len(tasks_fields)} задачи:\n{lines}")
