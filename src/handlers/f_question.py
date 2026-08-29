import base64
import logging

from aiogram.types import BufferedInputFile, Message

from src.core.message_text import extract_text
from src.integrations.claude_client import answer_question_rich
from src.integrations.web_search import answer_question

logger = logging.getLogger(__name__)

_PDF_MIME_TYPES = ("application/pdf",)


def _is_pdf(filename: str | None, mime_type: str | None) -> bool:
    if filename and filename.lower().endswith(".pdf"):
        return True
    return mime_type in _PDF_MIME_TYPES


async def handle_question(message: Message, text: str) -> None:
    """Свободный ввод без кнопки (auto-classify в orchestrator.py) —
    только текст, без файлов-приложений. Кнопочный поток см.
    handle_question_input ниже."""
    try:
        answer = await answer_question(text)
    except Exception:
        logger.exception("Не удалось ответить на вопрос: %r", text)
        await message.answer("Не получилось ответить, попробуй ещё раз.")
        return

    await message.answer(answer or "Не нашёл, что ответить.")


async def _build_content_blocks(message: Message) -> list[dict] | None:
    if message.photo:
        photo = message.photo[-1]
        file = await message.bot.download(photo.file_id)
        image_b64 = base64.b64encode(file.read()).decode()
        blocks: list[dict] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64},
            }
        ]
        if message.caption:
            blocks.append({"type": "text", "text": message.caption})
        return blocks

    if message.document:
        document = message.document
        if not _is_pdf(document.file_name, document.mime_type):
            return None
        file = await message.bot.download(document.file_id)
        pdf_b64 = base64.b64encode(file.read()).decode()
        blocks = [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
            }
        ]
        if message.caption:
            blocks.append({"type": "text", "text": message.caption})
        return blocks

    text = await extract_text(message)
    if not text:
        return None
    return [{"type": "text", "text": text}]


async def handle_question_input(message: Message) -> None:
    """Кнопка "Вопрос" — принимает текст/голос/фото/PDF, отвечает текстом
    и опциональным файлом-приложением. Обработка фото/PDF может занять
    время, поэтому сразу шлём подтверждение."""
    await message.answer("🔍 Вопрос взят в работу, отвечу через минуту-другую.")

    content_blocks = await _build_content_blocks(message)
    if content_blocks is None:
        await message.answer("Не смог обработать сообщение — поддерживаю текст, голос, фото и PDF.")
        return

    try:
        result = await answer_question_rich(content_blocks)
    except Exception:
        logger.exception("Не удалось ответить на вопрос (кнопка, мультимодальный ввод)")
        await message.answer("Не получилось ответить, попробуй ещё раз.")
        return

    await message.answer(result.reply_text or "Не нашёл, что ответить.")
    if result.attachment is not None:
        file = BufferedInputFile(
            result.attachment.content.encode("utf-8"), filename=result.attachment.filename
        )
        await message.answer_document(file)
