"""Наблюдение за внешними чатами через MTProto (Phase 87) — владелец
регистрирует чат (личную переписку или чужую группу, куда бота как
Bot API не позвать), сообщения копятся батчем и разбираются Claude по
заданному для этого чата промпту на заметки/задачи. Весь телетон-код
живёт в integrations/telegram_reader.py — этот модуль только бизнес-
логика (CRUD, батчинг, обработка), получает от обёртки готовые dict."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.sql import func

from src.core.bot_client import get_bot
from src.core.db import async_session
from src.core.notes import create_note
from src.integrations import telegram_reader
from src.integrations.claude_client import analyze_chat_batch
from src.models.chat_watch import WatchedChat, WatchedMessage
from src.models.task import Task

logger = logging.getLogger(__name__)

# Та же локальная копия, что adapters/api.py::_DEFAULT_PRIORITY — core не
# импортирует adapters (направление импорта только в обратную сторону).
_DEFAULT_PRIORITY = "средний"

# Фоновая обработка батча по size-триггеру не должна блокировать приём
# следующих сообщений (тот же strong-ref приём, что core/feedback.py —
# свой набор, не общий с другими модулями).
_background_tasks: set[asyncio.Task] = set()


def _serialize(chat: WatchedChat) -> dict:
    return {
        "id": chat.id,
        "telegram_chat_id": chat.telegram_chat_id,
        "title": chat.title,
        "chat_type": chat.chat_type,
        "custom_prompt": chat.custom_prompt,
        "enabled": chat.enabled,
        "batch_size_threshold": chat.batch_size_threshold,
        "batch_timeout_hours": chat.batch_timeout_hours,
    }


def _chat_tag(title: str) -> str:
    """slugify под core/notes.py::_normalize_tag (нижний регистр уже
    делает сама _normalize_tag — здесь только убираем то, что не
    пройдёт как читаемый тег)."""
    slug = "".join(c if c.isalnum() else "-" for c in title.strip().lower())
    slug = "-".join(filter(None, slug.split("-")))
    return slug or "chat"


# ---- Поиск/регистрация ---------------------------------------------------


async def search_watchable_chats(query: str) -> list[dict]:
    return await telegram_reader.search_dialogs(query)


async def resolve_forwarded_chat(forward_from_chat_id: int) -> dict | None:
    return await telegram_reader.resolve_forwarded_chat(forward_from_chat_id)


async def register_watched_chat(
    user_id: int, telegram_chat_id: int, title: str, chat_type: str, custom_prompt: str
) -> dict:
    """Повторная регистрация того же чата — обновление title/custom_prompt,
    не дубликат строки (UniqueConstraint(user_id, telegram_chat_id))."""
    async with async_session() as session:
        result = await session.execute(
            select(WatchedChat).where(
                WatchedChat.user_id == user_id, WatchedChat.telegram_chat_id == telegram_chat_id
            )
        )
        chat = result.scalar_one_or_none()
        if chat is None:
            chat = WatchedChat(
                user_id=user_id,
                telegram_chat_id=telegram_chat_id,
                title=title,
                chat_type=chat_type,
                custom_prompt=custom_prompt,
            )
            session.add(chat)
        else:
            chat.title = title
            chat.chat_type = chat_type
            chat.custom_prompt = custom_prompt
            chat.enabled = True
        await session.commit()
        await session.refresh(chat)
        return _serialize(chat)


async def list_watched_chats(user_id: int) -> list[dict]:
    async with async_session() as session:
        result = await session.execute(
            select(WatchedChat)
            .where(WatchedChat.user_id == user_id)
            .order_by(WatchedChat.created_at.desc())
        )
        return [_serialize(c) for c in result.scalars().all()]


async def set_watched_chat_enabled(
    watched_chat_id: int, user_id: int, enabled: bool
) -> dict | None:
    async with async_session() as session:
        chat = await session.get(WatchedChat, watched_chat_id)
        if chat is None or chat.user_id != user_id:
            return None
        chat.enabled = enabled
        await session.commit()
        await session.refresh(chat)
        return _serialize(chat)


async def update_watched_chat_prompt(
    watched_chat_id: int, user_id: int, custom_prompt: str
) -> dict | None:
    async with async_session() as session:
        chat = await session.get(WatchedChat, watched_chat_id)
        if chat is None or chat.user_id != user_id:
            return None
        chat.custom_prompt = custom_prompt
        await session.commit()
        await session.refresh(chat)
        return _serialize(chat)


async def remove_watched_chat(watched_chat_id: int, user_id: int) -> bool:
    """CASCADE снесёт и буферизованные WatchedMessage — минимальное
    хранение, снятие с наблюдения не должно оставлять хвостов."""
    async with async_session() as session:
        chat = await session.get(WatchedChat, watched_chat_id)
        if chat is None or chat.user_id != user_id:
            return False
        await session.delete(chat)
        await session.commit()
        return True


# ---- Приём сообщений и батчинг -------------------------------------------


def _display_name(sender: Any) -> str:
    if sender is None:
        return "неизвестно"
    username = getattr(sender, "username", None)
    if username:
        return f"@{username}"
    full = " ".join(
        filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)])
    )
    return full or str(getattr(sender, "id", "неизвестно"))


async def handle_incoming_event(event: Any) -> None:
    """Коллбэк для telegram_reader.register_handler — вызывается на ЛЮБОЕ
    входящее сообщение, фильтрация на "это наблюдаемый чат?" внутри
    ingest_message. Любая ошибка здесь не должна убить приём следующих
    событий у Telethon."""
    try:
        sender = await event.get_sender()
        await ingest_message(
            telegram_chat_id=event.chat_id,
            sender_telegram_id=getattr(sender, "id", None),
            sender_display_name=_display_name(sender),
            text=event.raw_text or "",
            sent_at=event.message.date,
        )
    except Exception:
        logger.exception("Не удалось обработать входящее сообщение наблюдаемого чата")


async def ingest_message(
    telegram_chat_id: int,
    sender_telegram_id: int | None,
    sender_display_name: str,
    text: str,
    sent_at: datetime,
) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(WatchedChat).where(
                WatchedChat.telegram_chat_id == telegram_chat_id, WatchedChat.enabled.is_(True)
            )
        )
        chat = result.scalar_one_or_none()
        if chat is None:
            return  # чат не зарегистрирован или наблюдение выключено — no-op

        session.add(
            WatchedMessage(
                watched_chat_id=chat.id,
                sender_telegram_id=sender_telegram_id,
                sender_display_name=sender_display_name,
                text=text,
                sent_at=sent_at,
            )
        )
        await session.commit()

        count_result = await session.execute(
            select(func.count(WatchedMessage.id)).where(WatchedMessage.watched_chat_id == chat.id)
        )
        count = count_result.scalar_one()
        watched_chat_id = chat.id
        threshold = chat.batch_size_threshold

    if count >= threshold:
        task = asyncio.create_task(process_batch(watched_chat_id))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def sweep_timed_out_batches(user_id: int) -> None:
    """Вызывается планировщиком (scheduler/jobs.py) — уже внутри
    await-коллбэка, не нужен fire-and-forget. Для каждого enabled чата
    этого пользователя с буфером старше batch_timeout_hours — await
    process_batch напрямую."""
    async with async_session() as session:
        result = await session.execute(
            select(WatchedChat).where(WatchedChat.user_id == user_id, WatchedChat.enabled.is_(True))
        )
        chats = result.scalars().all()
        due_ids: list[int] = []
        for chat in chats:
            oldest_result = await session.execute(
                select(func.min(WatchedMessage.sent_at)).where(
                    WatchedMessage.watched_chat_id == chat.id
                )
            )
            oldest = oldest_result.scalar_one_or_none()
            if oldest is None:
                continue
            age_hours = (datetime.now(oldest.tzinfo) - oldest).total_seconds() / 3600
            if age_hours >= chat.batch_timeout_hours:
                due_ids.append(chat.id)

    for watched_chat_id in due_ids:
        await process_batch(watched_chat_id)


async def process_batch(watched_chat_id: int) -> None:
    """Открывает свои сессии (не сессию вызывающего) — та же дисциплина,
    что core/feedback.py::_triage_background. Любое исключение здесь
    логируется, а не бросается наружу: следующий size/time-триггер
    просто повторит попытку на том же буфере, если он не был удалён."""
    try:
        async with async_session() as session:
            chat = await session.get(WatchedChat, watched_chat_id)
            if chat is None:
                return
            result = await session.execute(
                select(WatchedMessage)
                .where(WatchedMessage.watched_chat_id == watched_chat_id)
                .order_by(WatchedMessage.sent_at.asc())
            )
            messages = result.scalars().all()
            if not messages:
                return  # гонка size/time-триггеров на один чат — безопасный выход

            transcript = "\n".join(
                f"[{m.sent_at.strftime('%H:%M')}] {m.sender_display_name}: {m.text}"
                for m in messages
            )
            message_ids = [m.id for m in messages]
            user_id = chat.user_id
            title = chat.title
            custom_prompt = chat.custom_prompt

        analysis = await analyze_chat_batch(custom_prompt, transcript)

        tag = _chat_tag(title)
        for note_text in analysis.notes:
            await create_note(user_id, note_text, tags=[tag])

        if analysis.tasks:
            async with async_session() as session:
                for task_title in analysis.tasks:
                    session.add(
                        Task(
                            user_id=user_id,
                            title=task_title,
                            priority=_DEFAULT_PRIORITY,
                            source="chat_watch",
                            sort_order=time.time(),
                        )
                    )
                await session.commit()

        if analysis.notes or analysis.tasks:
            lines = [f"Из «{title}»: {len(analysis.notes)} заметок, {len(analysis.tasks)} задач."]
            lines.extend(f"— {t}" for t in analysis.tasks)
            try:
                await get_bot().send_message(user_id, "\n".join(lines))
            except Exception:
                logger.exception("Не удалось уведомить о батче watched_chat=%s", watched_chat_id)

        async with async_session() as session:
            await session.execute(
                WatchedMessage.__table__.delete().where(WatchedMessage.id.in_(message_ids))
            )
            await session.commit()
    except Exception:
        logger.exception("Не удалось обработать батч watched_chat=%s", watched_chat_id)
