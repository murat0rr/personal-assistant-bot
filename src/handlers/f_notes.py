import logging

from aiogram.types import Message

from src.core.config import settings
from src.core.notes import create_note

logger = logging.getLogger(__name__)


async def handle_note(message: Message, text: str) -> None:
    # Заметки пока доступны только основному владельцу (Phase 40, то же
    # решение, что для дневника, см. api.py::_NOT_READY_FOR_OTHERS и
    # TECHDEBT.md) — хранилище сменилось на Postgres (Phase 62), это
    # ограничение отдельное и им не затронуто.
    if not message.from_user or message.from_user.id != settings.telegram_user_id:
        await message.answer("Заметки пока доступны только основному пользователю.")
        return

    try:
        note = await create_note(message.from_user.id, text)
    except Exception:
        logger.exception("Не удалось сохранить заметку: %r", text)
        await message.answer("Не получилось сохранить заметку, попробуй ещё раз.")
        return

    # Заголовок (Phase 84) — почти всегда есть, ИИ подбирает синхронно
    # внутри create_note; None — редкий случай сбоя самого вызова к
    # Claude (см. core/notes.py::_maybe_generate_title, отдельно
    # отловлен там же, не валит создание заметки целиком).
    reply = f"Записал заметку «{note['title']}»." if note["title"] else "Записал заметку."
    if note["tags"]:
        reply += " Теги: " + ", ".join(f"#{t}" for t in note["tags"])
    await message.answer(reply)
