import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

logger = logging.getLogger(__name__)

ACK_TEXT = "⏳ Взял в работу…"
_NOT_UNDERSTOOD_TEXT = "Не смог разобрать сообщение, попробуй ещё раз."
_CRASHED_TEXT = "Что-то пошло не так, попробуй ещё раз."


class _Ack:
    """Уже отправленное «взял в работу» — первый ответ хендлера правит
    именно его (см. reply), а не шлёт новое сообщение."""

    def __init__(self, sent: Message) -> None:
        self.sent = sent
        self.used = False


# Хендлеры зовут reply(message, ...) без явной передачи ack — ContextVar
# ограничен задачей одного апдейта (aiogram обрабатывает каждый в своей),
# параллельные сообщения разных пользователей друг друга не видят.
_current: ContextVar[_Ack | None] = ContextVar("current_ack", default=None)


async def _finish_unused(ack: _Ack, text: str) -> None:
    """Хендлер закончил, не ответив (или упал) — не оставляем «⏳ Взял в
    работу…» висеть вечно."""
    if ack.used:
        return
    ack.used = True
    try:
        await ack.sent.edit_text(text)
    except Exception:
        logger.info("Не удалось поправить ack-сообщение (%s)", ack.sent.message_id)


@asynccontextmanager
async def working(message: Message) -> AsyncIterator[None]:
    """Phase 101 (фидбек): на каждый запрос сразу «взял в работу», пока
    идёт обработка — «печатает…», а итоговый ответ хендлера правит это же
    сообщение (reply ниже). Оборачивать нужно ДО extract_text — расшифровка
    голоса (STT) тоже медленная. Ошибка самой отправки ack не должна
    ломать обработку — тогда просто работаем как раньше, без него."""
    ack: _Ack | None = None
    try:
        ack = _Ack(await message.answer(ACK_TEXT))
    except Exception:
        logger.exception("Не удалось отправить ack «взял в работу»")

    token = _current.set(ack)
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            yield
    except BaseException:
        if ack is not None:
            await _finish_unused(ack, _CRASHED_TEXT)
        raise
    else:
        if ack is not None:
            await _finish_unused(ack, _NOT_UNDERSTOOD_TEXT)
    finally:
        _current.reset(token)


async def reply(message: Message, text: str, **kwargs: Any) -> Message | bool:
    """Ответ хендлера: первый за запрос правит ack-сообщение, остальные (и
    любой вызов вне working) — обычный message.answer. Если правка не
    удалась (сообщение удалили, слишком длинный текст, reply_markup,
    который edit_text не принимает) — ответ всё равно доходит новым
    сообщением, а ack убирается, чтобы не висел «⏳»."""
    ack = _current.get()
    if ack is not None and not ack.used:
        ack.used = True
        try:
            return await ack.sent.edit_text(text, **kwargs)
        except Exception:
            logger.info(
                "Не удалось поправить ack-сообщение (%s) — отвечаю новым", ack.sent.message_id
            )
            try:
                await ack.sent.delete()
            except Exception:
                pass
    return await message.answer(text, **kwargs)
