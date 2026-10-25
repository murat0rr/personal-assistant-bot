import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import yt_dlp
from yt_dlp.utils import DownloadError

logger = logging.getLogger(__name__)

# Доверенные видеохосты (Phase 102): ссылка на любой другой домен — это не
# видео для разбора, а обычный текст сообщения (защита от того, чтобы бот
# ходил по произвольным адресам, SSRF).
_ALLOWED_HOSTS = ("youtube.com", "youtu.be", "rutube.ru", "vk.com", "vkvideo.ru", "vimeo.com")

MAX_DURATION_SECONDS = 2 * 60 * 60
DEFAULT_PROMPT = "Сделай краткое саммари видео."

_EXTRACT_TIMEOUT_SECONDS = 90
_DOWNLOAD_TIMEOUT_SECONDS = 20
_MAX_SUBTITLE_BYTES = 10 * 1024 * 1024
# Склеиваем соседние реплики субтитров в строки по ~столько секунд — иначе
# автосубтитры YouTube (по 2-3 слова на реплику) раздувают транскрипт
# таймкодами в разы.
_LINE_SPAN_SECONDS = 30

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}»…"


class VideoError(Exception):
    """Ожидаемая причина, по которой видео не получилось разобрать —
    текст `user_message` показывается пользователю как есть."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class VideoRequest:
    url: str
    prompt: str
    extra_links: int = 0


@dataclass(frozen=True)
class VideoContent:
    url: str
    title: str
    channel: str | None
    duration_seconds: int | None
    transcript: str
    language: str
    auto_generated: bool
    # Шаблон ссылки «на момент» — только там, где такие ссылки точно
    # работают (YouTube); для остальных хостов модель ограничивается [мм:сс].
    timestamp_link_base: str | None


def _is_allowed_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in _ALLOWED_HOSTS)


def extract_video_request(text: str) -> VideoRequest | None:
    """Ссылка на поддерживаемый видеохост в тексте -> (ссылка, промпт).
    Промпт — всё остальное сообщение; пусто -> стандартное саммари. Если
    ссылок несколько, берётся первая, остальные просто считаются."""
    found: list[tuple[str, str]] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if _is_allowed_host(urlparse(url).hostname):
            found.append((match.group(0), url))
    if not found:
        return None

    raw, url = found[0]
    prompt = " ".join(text.replace(raw, " ", 1).split())
    return VideoRequest(url=url, prompt=prompt or DEFAULT_PROMPT, extra_links=len(found) - 1)


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_json3(data: str) -> list[tuple[float, str]]:
    cues: list[tuple[float, str]] = []
    for event in json.loads(data).get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(seg.get("utf8", "") for seg in segs).replace("\n", " ").strip()
        if text:
            cues.append((event.get("tStartMs", 0) / 1000, text))
    return cues


_VTT_TIME_RE = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:\d+:)?\d{2}:\d{2}[.,]\d{3}"
)
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def parse_vtt(data: str) -> list[tuple[float, str]]:
    cues: list[tuple[float, str]] = []
    start: float | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal start, buffer
        if start is not None:
            text = " ".join(buffer).strip()
            if text:
                cues.append((start, text))
        start, buffer = None, []

    for line in data.splitlines():
        match = _VTT_TIME_RE.search(line)
        if match:
            flush()
            hours, minutes, secs, millis = match.groups()
            start = int(hours or 0) * 3600 + int(minutes) * 60 + int(secs) + int(millis) / 1000
        elif not line.strip():
            flush()
        elif start is not None:
            cleaned = _VTT_TAG_RE.sub("", line).strip()
            if cleaned:
                buffer.append(cleaned)
    flush()
    return cues


def build_transcript(cues: list[tuple[float, str]]) -> str:
    """Реплики -> строки вида `[мм:сс] текст`. Автосубтитры YouTube
    перекрываются (каждая следующая реплика повторяет хвост предыдущей) —
    подряд идущие дубли выкидываем."""
    lines: list[str] = []
    line_start: float | None = None
    parts: list[str] = []
    previous = ""

    for start, text in cues:
        if text == previous:
            continue
        previous = text
        if line_start is None:
            line_start = start
        elif start - line_start >= _LINE_SPAN_SECONDS:
            lines.append(f"[{_format_timestamp(line_start)}] {' '.join(parts)}")
            line_start, parts = start, []
        parts.append(text)

    if line_start is not None and parts:
        lines.append(f"[{_format_timestamp(line_start)}] {' '.join(parts)}")
    return "\n".join(lines)


def _pick_format(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ext in ("json3", "vtt"):
        for fmt in formats:
            if fmt.get("ext") == ext and fmt.get("url"):
                return fmt
    return None


def _pick_track(info: dict[str, Any]) -> tuple[str, dict[str, Any], bool] | None:
    """Какие субтитры брать: ручные ru/en -> любые ручные -> автосубтитры на
    языке оригинала (`*-orig`) -> автосубтитры ru/en -> любые. У YouTube в
    автосубтитрах «ru» для английского ролика — машинный перевод, поэтому
    язык оригинала идёт раньше."""
    manual: dict[str, list] = info.get("subtitles") or {}
    auto: dict[str, list] = info.get("automatic_captions") or {}

    order: list[tuple[str, bool]] = []
    order += [(lang, False) for lang in ("ru", "en")]
    order += [(lang, False) for lang in manual if lang not in ("ru", "en")]
    order += [(lang, True) for lang in auto if lang.endswith("-orig")]
    order += [(lang, True) for lang in ("ru", "en")]
    order += [(lang, True) for lang in auto]

    for lang, is_auto in order:
        formats = (auto if is_auto else manual).get(lang)
        if not formats:
            continue
        fmt = _pick_format(formats)
        if fmt:
            return lang, fmt, is_auto
    return None


def _extract_info_sync(url: str) -> dict[str, Any]:
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 15,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


async def _extract_info(url: str) -> dict[str, Any]:
    return await asyncio.wait_for(
        asyncio.to_thread(_extract_info_sync, url), timeout=_EXTRACT_TIMEOUT_SECONDS
    )


async def _download_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as http:
        response = await http.get(url)
        response.raise_for_status()
        if len(response.content) > _MAX_SUBTITLE_BYTES:
            raise VideoError("Субтитры слишком большие, не смог их обработать.")
        return response.text


def _explain_download_error(error: DownloadError) -> str:
    message = str(error).lower()
    if "sign in to confirm" in message or "not a bot" in message:
        logger.warning("Видеохост требует подтверждения, что это не бот: %s", error)
        return "Видеохост не отдаёт данные этому серверу (просит подтвердить, что я не бот)."
    if "private" in message:
        return "Это закрытое видео — у меня нет к нему доступа."
    if "geo" in message or "not available in your country" in message:
        return "Это видео недоступно из страны, где работает бот."
    if "unavailable" in message or "not found" in message or "removed" in message:
        return "Видео недоступно (удалено или ссылка неверная)."
    if "age" in message and "restrict" in message:
        return "Видео с возрастным ограничением — не могу его открыть."
    logger.warning("yt-dlp не смог открыть видео: %s", error)
    return "Не получилось открыть это видео, попробуй другую ссылку."


async def fetch_video(url: str) -> VideoContent:
    try:
        info = await _extract_info(url)
    except TimeoutError:
        raise VideoError("Видеохост слишком долго отвечает, попробуй позже.") from None
    except DownloadError as error:
        raise VideoError(_explain_download_error(error)) from None
    except VideoError:
        raise
    except Exception:
        logger.exception("Неожиданная ошибка yt-dlp для %s", url)
        raise VideoError("Не получилось открыть это видео, попробуй другую ссылку.") from None

    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise VideoError("Это прямая трансляция — разберу её, когда она закончится.")

    duration = info.get("duration")
    if duration and duration > MAX_DURATION_SECONDS:
        raise VideoError(
            f"Видео длиннее {MAX_DURATION_SECONDS // 3600} часов "
            f"({_format_timestamp(duration)}) — пока не берусь за такие."
        )

    picked = _pick_track(info)
    if picked is None:
        raise VideoError(
            "У этого видео нет субтитров (ни ручных, ни автоматических) — по звуку пока не умею."
        )
    language, fmt, auto_generated = picked

    try:
        raw = await _download_text(fmt["url"])
        cues = parse_json3(raw) if fmt["ext"] == "json3" else parse_vtt(raw)
    except VideoError:
        raise
    except Exception:
        logger.exception("Не удалось скачать/разобрать субтитры (%s, %s)", url, language)
        raise VideoError("Не получилось загрузить субтитры этого видео.") from None

    transcript = build_transcript(cues)
    if not transcript:
        raise VideoError("Субтитры у видео пустые — разбирать нечего.")

    video_id = info.get("id")
    is_youtube = (info.get("extractor_key") or "").lower().startswith("youtube")
    return VideoContent(
        url=url,
        title=info.get("title") or "Без названия",
        channel=info.get("channel") or info.get("uploader"),
        duration_seconds=int(duration) if duration else None,
        transcript=transcript,
        language=language,
        auto_generated=auto_generated,
        timestamp_link_base=f"https://youtu.be/{video_id}?t=" if is_youtube and video_id else None,
    )
