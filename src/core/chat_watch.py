"""Наблюдение за каналами/группами через Bot API (Phase 99, заменяет
MTProto-подход Phase 87) — любой авторизованный пользователь
регистрирует канал (бот — админ) или группу (бот — участник), куда он
сам добавил бота; сообщения копятся батчем и разбираются Claude по
заданному для этого чата промпту на заметки/задачи. Приём сообщений —
handlers/f_chat_watch.py (channel_post/message хендлеры aiogram), этот
модуль — только бизнес-логика (CRUD, батчинг, обработка)."""

import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.sql import func

from src.core.bot_client import get_bot
from src.core.db import async_session
from src.core.notes import create_note
from src.core.user_profile import get_profile_summary
from src.integrations.claude_client import analyze_chat_batch
from src.models.chat_watch import WatchedChat, WatchedMessage
from src.models.note import Note, NoteTag, Tag
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


# ---- Регистрация ----------------------------------------------------------


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


async def ingest_message(
    telegram_chat_id: int,
    sender_telegram_id: int | None,
    sender_display_name: str,
    text: str,
    sent_at: datetime,
) -> None:
    """Вызывается из handlers/f_chat_watch.py на каждый принятый пост
    канала/сообщение группы. Один и тот же telegram_chat_id может быть
    зарегистрирован НЕСКОЛЬКИМИ пользователями (общий публичный канал) —
    у каждого свой критерий и свой буфер, поэтому разбираем все
    совпадения, а не только первое."""
    due_ids: list[int] = []
    async with async_session() as session:
        result = await session.execute(
            select(WatchedChat).where(
                WatchedChat.telegram_chat_id == telegram_chat_id, WatchedChat.enabled.is_(True)
            )
        )
        chats = result.scalars().all()
        if not chats:
            return  # чат не зарегистрирован ни у кого или наблюдение выключено — no-op

        for chat in chats:
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

        for chat in chats:
            count_result = await session.execute(
                select(func.count(WatchedMessage.id)).where(
                    WatchedMessage.watched_chat_id == chat.id
                )
            )
            if count_result.scalar_one() >= chat.batch_size_threshold:
                due_ids.append(chat.id)

    for watched_chat_id in due_ids:
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

        profile_summary = await get_profile_summary(user_id)
        analysis = await analyze_chat_batch(custom_prompt, transcript, profile_summary)

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


# ---- Секция дайджеста (Phase 99) ------------------------------------------

_DIGEST_PREVIEWS_PER_CHAT = 2


async def digest_summary_lines(user_id: int, since: datetime) -> list[str]:
    """Для утреннего дайджеста (handlers/f12_briefing.py) — по каждому
    наблюдаемому чату пользователя, где после `since` появились заметки
    (найденные через тег _chat_tag(title), которым create_note помечает
    каждую заметку из process_batch выше), строка со счётом + пара
    превью. Задачи сюда не попадают — они уже уходят владельцу
    немедленно при обработке батча (process_batch выше)."""
    async with async_session() as session:
        chats = (
            (
                await session.execute(
                    select(WatchedChat).where(
                        WatchedChat.user_id == user_id, WatchedChat.enabled.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        if not chats:
            return []

        lines: list[str] = []
        for chat in chats:
            result = await session.execute(
                select(Note.text)
                .join(NoteTag, NoteTag.note_id == Note.id)
                .join(Tag, Tag.id == NoteTag.tag_id)
                .where(
                    Tag.user_id == user_id,
                    Tag.name == _chat_tag(chat.title),
                    Note.created_at >= since,
                )
                .order_by(Note.created_at.desc())
            )
            texts = result.scalars().all()
            if not texts:
                continue
            lines.append(f"«{chat.title}»: {len(texts)} новых заметок")
            lines.extend(f"  • {t[:80]}" for t in texts[:_DIGEST_PREVIEWS_PER_CHAT])
        return lines
