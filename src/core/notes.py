from src.core.db import async_session
from src.models.note import Note


async def create_note(user_id: int, text: str) -> Note:
    """Сохраняет заметку (Phase 62 — раньше писала в Notion, см.
    handlers/f_notes.py::handle_note). Простой insert, в отличие от
    дневника (core/day_reviews.py::save_diary_entry) заметок за день
    может быть сколько угодно, апсертить нечего."""
    async with async_session() as session:
        note = Note(user_id=user_id, text=text)
        session.add(note)
        await session.commit()
        await session.refresh(note)
        return note
