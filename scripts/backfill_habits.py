"""Разовый перенос привычек из Notion в новую Postgres-таблицу habits
(Phase 10 — Tasks/Habits переезжают на Postgres как источник правды).

Самодостаточен — не зависит от src/integrations/notion.py (там функции
create_habit/list_habits/get_habit/update_habit_check удаляются в этой же
фазе) и не зависит от src.core.config.Settings (NOTION_TASKS_DB_ID и
NOTION_HABITS_DB_ID там тоже удаляются вместе с этой фазой — они больше
не нужны приложению) — читает их напрямую из окружения. .env всё ещё
пробрасывается в контейнер целиком (env_file в docker-compose.yml),
поэтому значения там доступны, даже если Settings их больше не объявляет.
Можно запустить в любой момент, до или после деплоя кода: сами страницы
в Notion никуда не деваются, просто приложение перестаёт их читать.

Запуск на сервере:
    docker compose exec -T api python -m scripts.backfill_habits
"""

import asyncio
import os
from datetime import date

from notion_client import AsyncClient

from src.core.db import async_session
from src.models.habit import Habit


def _read_text(prop: dict | None) -> str:
    if not prop:
        return ""
    if "rich_text" in prop:
        return "".join(part["plain_text"] for part in prop["rich_text"])
    if prop.get("select"):
        return prop["select"]["name"]
    if prop.get("status"):
        return prop["status"]["name"]
    if "multi_select" in prop:
        return ", ".join(item["name"] for item in prop["multi_select"])
    if "title" in prop:
        return "".join(part["plain_text"] for part in prop["title"])
    return ""


def _read_number(prop: dict | None) -> float | None:
    if not prop:
        return None
    if "number" in prop:
        return prop["number"]
    text = _read_text(prop)
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _read_date(prop: dict | None) -> date | None:
    if not prop:
        return None
    raw = prop.get("date")
    return date.fromisoformat(raw["start"][:10]) if raw else None


async def _fetch_notion_habits(client: AsyncClient, habits_db_id: str) -> list[dict]:
    db = await client.databases.retrieve(database_id=habits_db_id)
    data_source_id = db["data_sources"][0]["id"]

    habits: list[dict] = []
    cursor: str | None = None
    while True:
        kwargs: dict = {"data_source_id": data_source_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = await client.data_sources.query(**kwargs)
        for page in response["results"]:
            props = page["properties"]
            habits.append(
                {
                    "name": _read_text(props.get("Name")) or "(без названия)",
                    "streak": int(_read_number(props.get("Streak")) or 0),
                    "last_checked": _read_date(props.get("Last checked")),
                    "target_frequency": _read_text(props.get("Target frequency")) or "daily",
                }
            )
        if not response.get("has_more"):
            break
        cursor = response["next_cursor"]
    return habits


async def main() -> None:
    habits_db_id = os.environ.get("NOTION_HABITS_DB_ID", "")
    if not habits_db_id:
        print("NOTION_HABITS_DB_ID не задан — переносить нечего.")
        return

    client = AsyncClient(auth=os.environ.get("NOTION_API_KEY", ""))
    habits = await _fetch_notion_habits(client, habits_db_id)

    async with async_session() as session:
        for h in habits:
            session.add(Habit(**h))
        await session.commit()

    print(f"Перенесено привычек: {len(habits)}")


if __name__ == "__main__":
    asyncio.run(main())
