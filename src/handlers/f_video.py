import logging
import re

from aiogram.types import BufferedInputFile, LinkPreviewOptions, Message

from src.core.ack import reply
from src.core.video_answer import answer_about_video
from src.integrations.video import VideoError, VideoRequest, fetch_video

logger = logging.getLogger(__name__)

# Лимит Telegram — 4096; оставляем запас под приписки.
_CHAT_LIMIT = 3500
_SEPARATOR_RE = re.compile(r"^\s*---+\s*$", re.MULTILINE)
_FILE_NOTE = "\n\n📎 Подробный ответ — файлом ниже."


def split_answer(answer: str) -> tuple[str, str | None]:
    """«Кратко + файл» (Phase 102): короткий ответ идёт одним сообщением;
    длинный — в чат только краткий итог (до разделителя `---`, который
    просит поставить промпт), полный текст — файлом. Если разделителя нет,
    а текст не влезает — в чат первая часть по границе абзаца."""
    answer = answer.strip()
    if len(answer) <= _CHAT_LIMIT:
        return answer, None

    parts = _SEPARATOR_RE.split(answer, maxsplit=1)
    head = parts[0].strip()
    full = "\n\n".join(p.strip() for p in parts if p.strip())
    if len(parts) == 2 and head and len(head) <= _CHAT_LIMIT:
        return head + _FILE_NOTE, full

    cut = answer.rfind("\n\n", 0, _CHAT_LIMIT)
    if cut < _CHAT_LIMIT // 2:
        cut = answer.rfind("\n", 0, _CHAT_LIMIT)
    if cut < _CHAT_LIMIT // 2:
        cut = _CHAT_LIMIT
    return answer[:cut].rstrip() + "…" + _FILE_NOTE, answer


async def handle_video(message: Message, request: VideoRequest) -> None:
    """Ссылка на видео + промпт (Phase 102): субтитры -> Claude -> ответ.
    Вызывается внутри core/ack.py::working — ответ правит «⏳ Взял в работу…»."""
    try:
        video = await fetch_video(request.url)
    except VideoError as error:
        await reply(message, error.user_message)
        return

    try:
        answer = await answer_about_video(video, request.prompt)
    except Exception:
        logger.exception("Не удалось ответить по видео: %s", request.url)
        await reply(message, "Не получилось ответить по этому видео, попробуй ещё раз.")
        return

    chat_text, file_text = split_answer(answer)
    if request.extra_links:
        chat_text += "\n\n(В сообщении было несколько ссылок — разобрал первую.)"

    await reply(
        message,
        chat_text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    if file_text is not None:
        document = BufferedInputFile(
            f"{video.title}\n{video.url}\n\n{file_text}\n".encode(), filename="video_answer.md"
        )
        await message.answer_document(document)
