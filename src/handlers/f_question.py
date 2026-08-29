import logging

from aiogram.types import Message

from src.integrations.web_search import answer_question

logger = logging.getLogger(__name__)


async def handle_question(message: Message, text: str) -> None:
    try:
        answer = await answer_question(text)
    except Exception:
        logger.exception("Не удалось ответить на вопрос: %r", text)
        await message.answer("Не получилось ответить, попробуй ещё раз.")
        return

    await message.answer(answer or "Не нашёл, что ответить.")
