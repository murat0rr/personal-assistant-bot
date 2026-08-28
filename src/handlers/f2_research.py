import logging

from aiogram.types import Message

from src.integrations.web_search import research_options

logger = logging.getLogger(__name__)


async def handle_research(message: Message, text: str) -> None:
    try:
        answer = await research_options(text)
    except Exception:
        logger.exception("Не удалось выполнить research по запросу: %r", text)
        await message.answer("Не получилось подобрать варианты, попробуй ещё раз.")
        return

    await message.answer(answer or "Не нашёл подходящих вариантов.")
