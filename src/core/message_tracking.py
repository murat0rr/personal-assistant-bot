import logging
from datetime import datetime
from typing import Any

from aiogram import Bot
from aiogram.types import Message, TelegramObject

from src.core.db import async_session
from src.models.chat_message import ChatMessage

logger = logging.getLogger(__name__)


async def _record(chat_id: int, message_id: int, sent_at: datetime) -> None:
    # Ошибка записи не должна ронять доставку/обработку сообщения —
    # автоочистка чата не критичный для работы бота функционал.
    try:
        async with async_session() as session:
            await session.merge(
                ChatMessage(chat_id=chat_id, message_id=message_id, sent_at=sent_at)
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Не удалось записать сообщение %s (чат %s) для автоочистки", message_id, chat_id
        )


async def _track_outgoing(make_request: Any, bot: Bot, method: Any) -> Any:
    result = await make_request(bot, method)
    if isinstance(result, Message):
        await _record(result.chat.id, result.message_id, result.date)
    return result


def attach_message_tracking(bot: Bot) -> None:
    """Отслеживать все исходящие сообщения этого Bot-инстанса — нужно
    вызывать для каждого процесса, который шлёт сообщения (bot и api)."""
    bot.session.middleware.register(_track_outgoing)


async def track_incoming(handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
    """outer_middleware для dp.message — отслеживает входящие сообщения."""
    if isinstance(event, Message):
        await _record(event.chat.id, event.message_id, event.date)
    return await handler(event, data)
