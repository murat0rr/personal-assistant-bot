import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core import video_answer
from src.handlers.f_video import split_answer
from src.integrations import video
from src.integrations.video import (
    DEFAULT_PROMPT,
    VideoError,
    build_transcript,
    extract_video_request,
    fetch_video,
    parse_json3,
    parse_vtt,
)

# ---- разбор ссылки и промпта ------------------------------------------------


def test_url_with_prompt():
    request = extract_video_request("сделай саммари https://www.youtube.com/watch?v=abc123 плиз")
    assert request is not None
    assert request.url == "https://www.youtube.com/watch?v=abc123"
    assert request.prompt == "сделай саммари плиз"
    assert request.extra_links == 0


def test_bare_url_gets_default_prompt():
    request = extract_video_request("https://youtu.be/abc123")
    assert request is not None
    assert request.prompt == DEFAULT_PROMPT


def test_trailing_punctuation_is_not_part_of_url():
    request = extract_video_request("что тут? (https://rutube.ru/video/abc/).")
    assert request is not None
    assert request.url == "https://rutube.ru/video/abc/"


@pytest.mark.parametrize(
    "url",
    [
        "https://vimeo.com/123456",
        "https://vk.com/video-1_2",
        "https://vkvideo.ru/video-1_2",
        "https://m.youtube.com/watch?v=abc",
        "https://music.youtube.com/watch?v=abc",
    ],
)
def test_supported_hosts(url):
    assert extract_video_request(f"саммари {url}") is not None


@pytest.mark.parametrize(
    "text",
    [
        "просто текст без ссылки",
        "https://example.com/watch?v=abc",
        "https://youtube.com.evil.com/watch?v=abc",
        "https://evil.com/?u=https://youtube.com/watch?v=abc",
        "http://169.254.169.254/latest/meta-data",
        "https://notyoutube.com/watch?v=abc",
    ],
)
def test_foreign_hosts_are_not_videos(text):
    assert extract_video_request(text) is None


def test_several_links_use_first_and_count_rest():
    request = extract_video_request("сравни https://youtu.be/aaa и https://youtu.be/bbb")
    assert request is not None
    assert request.url == "https://youtu.be/aaa"
    assert request.extra_links == 1


# ---- субтитры -> транскрипт -------------------------------------------------


def test_parse_json3():
    data = json.dumps(
        {
            "events": [
                {"tStartMs": 0, "segs": [{"utf8": "привет"}, {"utf8": " мир"}]},
                {"tStartMs": 1500},
                {"tStartMs": 2000, "segs": [{"utf8": "\n"}]},
                {"tStartMs": 61000, "segs": [{"utf8": "дальше"}]},
            ]
        }
    )
    assert parse_json3(data) == [(0.0, "привет мир"), (61.0, "дальше")]


def test_parse_vtt_strips_tags_and_joins_lines():
    data = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000 align:start\n"
        "<c>первая</c> строка\nвторая строка\n\n"
        "01:02:03.500 --> 01:02:05.000\n"
        "<00:01:02.600><c>поздно</c>\n"
    )
    assert parse_vtt(data) == [(1.0, "первая строка вторая строка"), (3723.5, "поздно")]


def test_build_transcript_merges_cues_and_drops_repeats():
    cues = [(0, "раз"), (5, "раз"), (10, "два"), (40, "три"), (95, "четыре")]
    assert build_transcript(cues) == "[00:00] раз два\n[00:40] три\n[01:35] четыре"


def test_build_transcript_uses_hours_for_long_videos():
    assert build_transcript([(3725, "поздно")]) == "[1:02:05] поздно"


def test_build_transcript_empty():
    assert build_transcript([]) == ""


# ---- выбор дорожки и fetch_video --------------------------------------------


def _fmt(ext, url="https://sub.example/x"):
    return {"ext": ext, "url": url}


def test_pick_track_prefers_manual_ru_over_auto():
    info = {
        "subtitles": {"ru": [_fmt("json3")]},
        "automatic_captions": {"ru-orig": [_fmt("json3")]},
    }
    lang, _, auto = video._pick_track(info)
    assert (lang, auto) == ("ru", False)


def test_pick_track_uses_original_language_auto_before_translated():
    info = {
        "subtitles": {},
        "automatic_captions": {
            "ru": [_fmt("json3")],  # машинный перевод английского ролика
            "en-orig": [_fmt("json3")],
        },
    }
    lang, _, auto = video._pick_track(info)
    assert (lang, auto) == ("en-orig", True)


def test_pick_track_prefers_json3_over_vtt_and_skips_unknown_formats():
    info = {"subtitles": {"en": [_fmt("ttml"), _fmt("vtt"), _fmt("json3")]}}
    _, fmt, _ = video._pick_track(info)
    assert fmt["ext"] == "json3"
    assert video._pick_track({"subtitles": {"en": [_fmt("ttml")]}}) is None


def _info(**overrides):
    info = {
        "id": "abc123",
        "title": "Лекция",
        "channel": "Канал",
        "duration": 600,
        "extractor_key": "Youtube",
        "subtitles": {"ru": [_fmt("json3")]},
        "automatic_captions": {},
    }
    info.update(overrides)
    return info


@pytest.fixture
def patch_fetch(monkeypatch):
    def apply(info, subtitle_text=None):
        monkeypatch.setattr(video, "_extract_info", AsyncMock(return_value=info))
        monkeypatch.setattr(
            video,
            "_download_text",
            AsyncMock(
                return_value=subtitle_text
                or json.dumps({"events": [{"tStartMs": 0, "segs": [{"utf8": "текст"}]}]})
            ),
        )

    return apply


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_fetch_video_ok(patch_fetch):
    patch_fetch(_info())
    content = await fetch_video("https://youtu.be/abc123")
    assert content.title == "Лекция"
    assert content.transcript == "[00:00] текст"
    assert content.language == "ru"
    assert content.auto_generated is False
    assert content.timestamp_link_base == "https://youtu.be/abc123?t="


@pytest.mark.anyio
async def test_fetch_video_non_youtube_has_no_timestamp_links(patch_fetch):
    patch_fetch(_info(extractor_key="Rutube"))
    content = await fetch_video("https://rutube.ru/video/abc/")
    assert content.timestamp_link_base is None


@pytest.mark.anyio
async def test_fetch_video_rejects_too_long(patch_fetch):
    patch_fetch(_info(duration=3 * 3600))
    with pytest.raises(VideoError, match="длиннее 2 часов"):
        await fetch_video("https://youtu.be/abc123")


@pytest.mark.anyio
async def test_fetch_video_rejects_live(patch_fetch):
    patch_fetch(_info(is_live=True))
    with pytest.raises(VideoError, match="трансляция"):
        await fetch_video("https://youtu.be/abc123")


@pytest.mark.anyio
async def test_fetch_video_without_subtitles(patch_fetch):
    patch_fetch(_info(subtitles={}, automatic_captions={}))
    with pytest.raises(VideoError, match="нет субтитров"):
        await fetch_video("https://youtu.be/abc123")


@pytest.mark.anyio
async def test_fetch_video_empty_subtitles(patch_fetch):
    patch_fetch(_info(), subtitle_text=json.dumps({"events": []}))
    with pytest.raises(VideoError, match="пустые"):
        await fetch_video("https://youtu.be/abc123")


@pytest.mark.anyio
async def test_fetch_video_maps_download_errors(monkeypatch):
    from yt_dlp.utils import DownloadError

    monkeypatch.setattr(
        video,
        "_extract_info",
        AsyncMock(side_effect=DownloadError("ERROR: Video unavailable. This video is private")),
    )
    with pytest.raises(VideoError, match="закрытое"):
        await fetch_video("https://youtu.be/abc123")


@pytest.mark.anyio
async def test_fetch_video_maps_bot_check(monkeypatch):
    from yt_dlp.utils import DownloadError

    monkeypatch.setattr(
        video,
        "_extract_info",
        AsyncMock(side_effect=DownloadError("Sign in to confirm you're not a bot")),
    )
    with pytest.raises(VideoError, match="не бот"):
        await fetch_video("https://youtu.be/abc123")


# ---- «кратко + файл» --------------------------------------------------------


def test_short_answer_stays_in_chat():
    assert split_answer("коротко") == ("коротко", None)


def test_long_answer_with_separator_splits_into_summary_and_file():
    answer = "Итог: кратко.\n---\n" + "подробности " * 600
    chat, file = split_answer(answer)
    assert chat.startswith("Итог: кратко.")
    assert "файлом" in chat
    assert file is not None and "подробности" in file and "---" not in file


def test_long_answer_without_separator_is_cut_at_paragraph():
    answer = "\n\n".join(["абзац " * 60] * 20).strip()
    chat, file = split_answer(answer)
    assert len(chat) < 4096
    assert chat.endswith("файлом ниже.")
    assert file == answer


# ---- ответ Claude -----------------------------------------------------------


def _fake_client(monkeypatch, texts):
    create = AsyncMock(
        side_effect=[
            SimpleNamespace(
                content=[SimpleNamespace(type="text", text=t)],
                stop_reason="end_turn",
                usage=SimpleNamespace(output_tokens=1),
            )
            for t in texts
        ]
    )
    monkeypatch.setattr(video_answer.client.messages, "create", create)
    return create


def _content(transcript):
    return video.VideoContent(
        url="https://youtu.be/abc123",
        title="Лекция",
        channel="Канал",
        duration_seconds=600,
        transcript=transcript,
        language="ru",
        auto_generated=True,
        timestamp_link_base="https://youtu.be/abc123?t=",
    )


def test_split_transcript_keeps_lines_whole():
    lines = [f"[00:{i:02d}] " + "слово " * 10 for i in range(50)]
    chunks = video_answer.split_transcript("\n".join(lines), chunk_chars=500)
    assert len(chunks) > 1
    assert "\n".join(chunks).split("\n") == lines


@pytest.mark.anyio
async def test_short_transcript_is_one_call_with_task_after_data(monkeypatch):
    create = _fake_client(monkeypatch, ["ответ"])
    result = await video_answer.answer_about_video(_content("[00:00] привет"), "что тут?")
    assert result == "ответ"
    assert create.await_count == 1
    content = create.await_args.kwargs["messages"][0]["content"]
    assert "<transcript>\n[00:00] привет\n</transcript>" in content
    assert content.rstrip().endswith("<task>\nчто тут?\n</task>")
    assert "ДАННЫЕ" in create.await_args.kwargs["system"]


@pytest.mark.anyio
async def test_long_transcript_goes_through_chunk_notes(monkeypatch):
    monkeypatch.setattr(video_answer, "SINGLE_PASS_MAX_CHARS", 100)
    monkeypatch.setattr(video_answer, "_CHUNK_CHARS", 120)
    transcript = "\n".join(f"[00:{i:02d}] " + "слово " * 8 for i in range(12))
    chunk_count = len(video_answer.split_transcript(transcript, 120))
    create = _fake_client(monkeypatch, [f"выписка {i}" for i in range(chunk_count)] + ["итог"])
    result = await video_answer.answer_about_video(_content(transcript), "саммари")
    assert result == "итог"
    assert create.await_count == chunk_count + 1
    final_content = create.await_args.kwargs["messages"][0]["content"]
    assert "Выписка из фрагмента 1" in final_content
    assert "слово слово" not in final_content  # сырого транскрипта в финале нет


@pytest.mark.anyio
async def test_empty_claude_answer_raises(monkeypatch):
    _fake_client(monkeypatch, [""])
    with pytest.raises(ValueError):
        await video_answer.answer_about_video(_content("[00:00] привет"), "что тут?")
