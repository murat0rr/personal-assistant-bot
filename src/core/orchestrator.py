import logging
import time

from aiogram import F, Router
from aiogram.types import Message

from src.core.ack import working
from src.core.auth import is_authorized
from src.core.llm_router import classify_intent
from src.core.message_text import extract_text
from src.handlers.f1_task_note import handle_task_note
from src.handlers.f_feedback import submit_feedback
from src.handlers.f_notes import handle_note
from src.handlers.f_question import handle_question
from src.handlers.f_reminders import handle_new_reminder
from src.handlers.f_video import handle_video
from src.integrations.video import extract_video_request

logger = logging.getLogger(__name__)

router = Router()

# voice-сообщение, либо текст, не являющийся командой (не начинается с "/")
_ROUTABLE_FILTER = F.voice | (F.text & ~F.text.startswith("/"))


@router.message(_ROUTABLE_FILTER)
async def route_message(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    async with working(message):
        # Замеры по шагам (тех-долг, владелец спросил 2026-10-22, сколько
        # времени создаются задачи — ответить было нечем, таймингов не
        # было вообще). t_text включает STT для голоса (extract_text сама
        # зовёт Whisper) — отдельно время STT не выделяем, голос и так
        # заметно дольше текста уже по этой сумме.
        t0 = time.perf_counter()
        text = await extract_text(message)
        t_text = time.perf_counter() - t0
        if not text:
            return

        # Ссылка на видео + промпт (Phase 102) — до классификации intent'а:
        # это отдельный сценарий, классификатору его угадывать незачем.
        video_request = extract_video_request(text)
        if video_request:
            await handle_video(message, video_request)
            return

        t1 = time.perf_counter()
        intent = await classify_intent(text)
        t_intent = time.perf_counter() - t1
        logger.info("intent=%s text=%r", intent, text)

        t2 = time.perf_counter()
        if intent == "note":
            await handle_note(message, text)
        elif intent == "question":
            await handle_question(message, text)
        elif intent == "reminder":
            await handle_new_reminder(message, text)
        elif intent == "feedback":
            await submit_feedback(message, text)
        else:
            await handle_task_note(message, text)
        t_handler = time.perf_counter() - t2

        logger.info(
            "timing route_message: text_extract=%.2fs classify_intent=%.2fs "
            "handler(%s)=%.2fs total=%.2fs",
            t_text,
            t_intent,
            intent,
            t_handler,
            t_text + t_intent + t_handler,
        )
