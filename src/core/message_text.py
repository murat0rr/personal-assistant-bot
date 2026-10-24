import logging

from aiogram.types import Message

from src.integrations.stt import stt

logger = logging.getLogger(__name__)


async def extract_text(message: Message) -> str | None:
    """Достать текст из сообщения: голос -> STT, иначе текст как есть.
    Общий хелпер для orchestrator.py и mode_buttons.py.

    Сбой STT (просроченный ключ Groq, недоступность сервиса и т.п.) —
    раньше падал необработанным исключением из route_message и
    аналогичных хендлеров: пользователь отправлял голосовое и просто
    не получал вообще никакого ответа, без единой подсказки, что
    что-то не так (обнаружено 2026-10-23: GROQ_API_KEY протух,
    8 голосовых подряд ушли в пустоту — ни один из ~12 мест вызова
    extract_text не оборачивал её в try/except, все одинаково трактуют
    falsy text как "ничего делать не нужно"). Ловим здесь, один раз —
    тот же приём, что у call_with_tool в claude_client.py: одна точка
    вместо дублирования try/except в каждом хендлере."""
    if message.voice:
        assert message.bot is not None
        file = await message.bot.get_file(message.voice.file_id)
        assert file.file_path is not None
        buf = await message.bot.download_file(file.file_path)
        assert buf is not None
        try:
            return await stt.transcribe(buf.read(), "voice.ogg")
        except Exception:
            logger.exception("Не удалось распознать голосовое сообщение")
            await message.answer(
                "Не получилось распознать голосовое — попробуй ещё раз или напиши текстом."
            )
            return None
    return message.text
