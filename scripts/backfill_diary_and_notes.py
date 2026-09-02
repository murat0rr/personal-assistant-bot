"""Разовый перенос дневника и заметок из Notion в Postgres (Phase 62 —
дневник/заметки переезжают на Postgres как источник правды, Notion
остаётся в репозитории неактивным до отдельного удаления в Phase 63).

В отличие от scripts/backfill_habits.py (Phase 10) — здесь
src/integrations/notion.py в этой фазе ещё не удаляется, поэтому скрипт
спокойно использует его (list_diary_entries/list_notes), не дублирует
парсинг Notion-страниц.

И дневник, и заметки — только у основного владельца (см.
handlers/f4_diary.py, handlers/f_notes.py), поэтому весь перенос идёт
на settings.telegram_user_id, других пользователей это не касается.

Дневник переносится через core.day_reviews.save_diary_entry — тот же
апсерт, что использует живой /дневник-опрос, поэтому повторный запуск
безопасен (перезапишет те же даты теми же значениями, не задублирует).
Заметки — простые insert (как и в живом /заметка), запись напрямую
через модель, чтобы сохранить исходное время создания
(created_at Note обычно проставляется server_default=now(), но здесь
важно перенести именно исходную дату заметки, а не дату переноса);
повторный запуск скрипта задублирует заметки — рассчитан на разовый
прогон.

Запуск на сервере (после деплоя кода этой фазы, до Phase 63):
    docker compose exec -T api uv run python -m scripts.backfill_diary_and_notes
"""

import asyncio
from datetime import datetime

from src.core.config import settings
from src.core.day_reviews import save_diary_entry
from src.core.db import async_session
from src.integrations.notion import list_diary_entries, list_notes
from src.models.note import Note

_RATING_FIELDS = ("physical", "social", "productivity", "happiness")


async def _backfill_diary() -> int:
    if not settings.notion_diary_db_id:
        print("NOTION_DIARY_DB_ID не задан — дневник переносить нечего.")
        return 0

    entries = await list_diary_entries()
    count = 0
    for entry in entries:
        entry_date = entry.get("entry_date")
        if entry_date is None:
            continue
        ratings = {field: entry.get(field) for field in _RATING_FIELDS}
        await save_diary_entry(
            settings.telegram_user_id,
            entry_date,
            ratings,
            entry.get("highlight"),
            entry.get("reflection"),
            entry.get("summary"),
        )
        count += 1
    return count


async def _backfill_notes() -> int:
    if not settings.notion_notes_db_id:
        print("NOTION_NOTES_DB_ID не задан — заметки переносить нечего.")
        return 0

    notes = await list_notes()
    count = 0
    async with async_session() as session:
        for n in notes:
            if not n["text"]:
                continue
            note = Note(user_id=settings.telegram_user_id, text=n["text"])
            created_time = n.get("created_time")
            if created_time:
                # Notion отдаёт ISO 8601 с суффиксом "Z" — datetime.fromisoformat
                # (до 3.11) его не понимает, заменяем на +00:00.
                note.created_at = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
            session.add(note)
            count += 1
        await session.commit()
    return count


async def main() -> None:
    diary_count = await _backfill_diary()
    notes_count = await _backfill_notes()
    print(f"Перенесено записей дневника: {diary_count}")
    print(f"Перенесено заметок: {notes_count}")


if __name__ == "__main__":
    asyncio.run(main())
