import asyncio
import logging

from src.core import prompts
from src.core.config import settings
from src.integrations.claude_client import client
from src.integrations.video import VideoContent

logger = logging.getLogger(__name__)

# Транскрипт до этого размера уходит в Sonnet целиком одним вызовом; длиннее
# (часовые лекции) — сначала выписки по кускам, потом итог по выпискам.
SINGLE_PASS_MAX_CHARS = 60_000
_CHUNK_CHARS = 40_000
_MAX_PARALLEL_CHUNKS = 3

# Прокси CLAUDE_BASE_URL тратит часть max_tokens на невидимый reasoning
# (см. TECHDEBT.md) — бюджет с большим запасом, не впритык.
_ANSWER_MAX_TOKENS = 8000
_NOTES_MAX_TOKENS = 4000


def split_transcript(transcript: str, chunk_chars: int | None = None) -> list[str]:
    """Режем по границам строк (`[мм:сс] ...`), чтобы не рвать реплику и
    не терять таймкод."""
    chunk_chars = chunk_chars or _CHUNK_CHARS
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in transcript.split("\n"):
        if current and size + len(line) + 1 > chunk_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _duration_text(seconds: int | None) -> str:
    if not seconds:
        return "неизвестна"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _meta_block(video: VideoContent) -> str:
    kind = "автоматические" if video.auto_generated else "ручные"
    lines = [
        f"Название: {video.title}",
        f"Канал: {video.channel or 'неизвестен'}",
        f"Длительность: {_duration_text(video.duration_seconds)}",
        f"Субтитры: {kind}, язык {video.language}",
    ]
    if video.timestamp_link_base:
        lines.append(f"База ссылок на моменты: {video.timestamp_link_base}")
    return "\n".join(lines)


def _user_content(meta: str, body_tag: str, body: str, task: str) -> str:
    return f"{meta}\n\n<{body_tag}>\n{body}\n</{body_tag}>\n\n<task>\n{task}\n</task>"


async def _complete(model: str, system: str, content: str, max_tokens: int) -> str:
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        logger.warning(
            "Claude вернул пустой ответ по видео (stop_reason=%s, output_tokens=%s)",
            response.stop_reason,
            getattr(response.usage, "output_tokens", None),
        )
        raise ValueError("Claude вернул пустой ответ")
    return text


async def answer_about_video(video: VideoContent, prompt: str) -> str:
    meta = _meta_block(video)

    if len(video.transcript) <= SINGLE_PASS_MAX_CHARS:
        return await _complete(
            settings.claude_model_sonnet,
            prompts.VIDEO_ANSWER,
            _user_content(meta, "transcript", video.transcript, prompt),
            _ANSWER_MAX_TOKENS,
        )

    chunks = split_transcript(video.transcript)
    semaphore = asyncio.Semaphore(_MAX_PARALLEL_CHUNKS)

    async def notes_for(index: int, chunk: str) -> str:
        async with semaphore:
            part_meta = f"{meta}\nФрагмент {index} из {len(chunks)}"
            return await _complete(
                settings.claude_model_haiku,
                prompts.VIDEO_CHUNK_NOTES,
                _user_content(part_meta, "transcript", chunk, prompt),
                _NOTES_MAX_TOKENS,
            )

    notes = await asyncio.gather(*(notes_for(i, c) for i, c in enumerate(chunks, 1)))
    combined = "\n\n".join(f"--- Выписка из фрагмента {i} ---\n{n}" for i, n in enumerate(notes, 1))
    return await _complete(
        settings.claude_model_sonnet,
        prompts.VIDEO_ANSWER
        + "\n\nВместо полного транскрипта тебе даны плотные выписки по фрагментам "
        "видео (внутри <transcript>) — отвечай по ним.",
        _user_content(meta, "transcript", combined, prompt),
        _ANSWER_MAX_TOKENS,
    )
