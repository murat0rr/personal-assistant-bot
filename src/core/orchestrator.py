import logging

from aiogram import F, Router
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.llm_router import classify_intent
from src.core.message_text import extract_text
from src.handlers.f1_task_note import handle_task_note
from src.handlers.f_notes import handle_note
from src.handlers.f_question import handle_question
from src.handlers.f_reminders import handle_new_reminder

logger = logging.getLogger(__name__)

router = Router()

# voice-сообщение, либо текст, не являющийся командой (не начинается с "/")
_ROUTABLE_FILTER = F.voice | (F.text & ~F.text.startswith("/"))


@router.message(_ROUTABLE_FILTER)
async def route_message(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    text = await extract_text(message)
    if not text:
        return

    intent = await classify_intent(text)
    logger.info("intent=%s text=%r", intent, text)

    if intent == "note":
        await handle_note(message, text)
    elif intent == "question":
        await handle_question(message, text)
    elif intent == "reminder":
        await handle_new_reminder(message, text)
    else:
        await handle_task_note(message, text)
