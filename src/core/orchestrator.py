import logging

from aiogram import F, Router
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.llm_router import classify_intent
from src.handlers.f1_task_note import handle_task_note
from src.handlers.f2_research import handle_research
from src.integrations.stt import stt

logger = logging.getLogger(__name__)

router = Router()

# voice-сообщение, либо текст, не являющийся командой (не начинается с "/")
_ROUTABLE_FILTER = F.voice | (F.text & ~F.text.startswith("/"))


async def _extract_text(message: Message) -> str | None:
    if message.voice:
        assert message.bot is not None
        file = await message.bot.get_file(message.voice.file_id)
        assert file.file_path is not None
        buf = await message.bot.download_file(file.file_path)
        assert buf is not None
        return await stt.transcribe(buf.read(), "voice.ogg")
    return message.text


@router.message(_ROUTABLE_FILTER)
async def route_message(message: Message) -> None:
    if not message.from_user or not is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    text = await _extract_text(message)
    if not text:
        return

    intent = await classify_intent(text)
    logger.info("intent=%s text=%r", intent, text)

    if intent == "research":
        await handle_research(message, text)
    else:
        await handle_task_note(message, text)
