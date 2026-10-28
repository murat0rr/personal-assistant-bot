import logging
import time
from datetime import datetime

from aiogram.types import Message

from src.core.ack import reply
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
    # Два РАЗНЫХ случая здесь ранее показывали пользователю один и тот же
    # текст "ИИ сейчас недоступен" (фидбек #15, 2026-10-26: "если ии не
    # распознал что-то, то выдается ответ что ии недоступен, хотя он
    # просто не дал ответ") — не различая их:
    # - ValueError из extract_tasks_fields — Claude РЕАЛЬНО ответил, просто
    #   не вызвал тул или вызвал его с пустым списком задач (см. ValueError
    #   там же) — не "недоступен", а "не понял"/"не нашёл задачу".
    # - любая другая Exception — настоящий сбой похода в Claude (прокси
    #   недоступен/таймаут/ошибка API) — здесь "недоступен" уместно.
    fallback_unavailable = False
    t0 = time.perf_counter()
    try:
        # Одно сообщение может называть несколько задач сразу (Phase 49) —
        # extract_tasks_fields всегда возвращает список, даже для обычного
        # однозадачного текста (тогда просто из одного элемента).
        tasks_fields = await extract_tasks_fields(text, today)
    except ValueError:
        logger.exception(
            "ИИ не нашёл задачу в сообщении — создаю задачу без деталей (фолбек): %r", text
        )
        tasks_fields = [_fallback_task_fields(text)]
        fallback_used = True
    except Exception:
        logger.exception("ИИ недоступен — создаю задачу без деталей (фолбек): %r", text)
        tasks_fields = [_fallback_task_fields(text)]
        fallback_used = True
        fallback_unavailable = True
    t_ai = time.perf_counter() - t0

    t1 = time.perf_counter()
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
                    physical_load=fields.physical_load,
                    mental_load=fields.mental_load,
                    emotional_load=fields.emotional_load,
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
        await reply(message, "Не получилось создать задачу, попробуй ещё раз.")
        return
    t_db = time.perf_counter() - t1

    logger.info(
        "timing handle_task_note: extract_tasks_fields=%.2fs db=%.2fs fallback=%s",
        t_ai,
        t_db,
        fallback_used,
    )

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
        reason = "ИИ сейчас недоступен" if fallback_unavailable else "Не разобрал запрос"
        await reply(
            message,
            f"{reason} — сохранил как есть: «{tasks_fields[0].title}» "
            "(без срока, приоритет: средний). Поправь вручную, если нужно.",
        )
        return

    def _line(fields) -> str:
        due_str = fields.due_date.strftime("%d.%m.%Y") if fields.due_date else "без срока"
        return f"«{fields.title}» ({due_str}, приоритет: {fields.priority})"

    if len(tasks_fields) == 1:
        await reply(message, f"Готово: {_line(tasks_fields[0])}")
    else:
        lines = "\n".join(f"— {_line(f)}" for f in tasks_fields)
        await reply(message, f"Готово, создал {len(tasks_fields)} задачи:\n{lines}")
