from datetime import date
from typing import Any

from notion_client import AsyncClient

from src.core.config import settings

_client = AsyncClient(auth=settings.notion_api_key)


async def _get_data_source(database_id: str) -> tuple[str, dict[str, Any]]:
    db = await _client.databases.retrieve(database_id=database_id)
    data_source_id = db["data_sources"][0]["id"]
    data_source = await _client.data_sources.retrieve(data_source_id=data_source_id)
    return data_source_id, data_source["properties"]


_RATING_PROPERTY_NAMES = {
    "physical": "Physical",
    "social": "Social",
    "productivity": "Productivity",
    "happiness": "Happiness",
}


async def create_diary_entry(
    entry_date: date,
    ratings: dict[str, int],
    highlight: str | None,
    reflection: str | None,
    summary: str | None,
) -> str:
    """Записать вечерний дневник. Поля заполняются, только если реально
    есть в схеме базы — тот же адаптивный паттерн, что был у create_task."""
    data_source_id, schema = await _get_data_source(settings.notion_diary_db_id)
    properties: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": entry_date.isoformat()}}]},
    }
    if "Date" in schema:
        properties["Date"] = {"date": {"start": entry_date.isoformat()}}

    for field, notion_name in _RATING_PROPERTY_NAMES.items():
        value = ratings.get(field)
        if notion_name in schema and value is not None:
            properties[notion_name] = {"number": value}

    if highlight and "Highlight" in schema:
        properties["Highlight"] = {"rich_text": [{"text": {"content": highlight[:2000]}}]}
    if reflection and "Reflection" in schema:
        properties["Reflection"] = {"rich_text": [{"text": {"content": reflection[:2000]}}]}
    if summary and "Summary" in schema:
        properties["Summary"] = {"rich_text": [{"text": {"content": summary[:2000]}}]}

    page = await _client.pages.create(
        parent={"type": "data_source_id", "data_source_id": data_source_id},
        properties=properties,
    )
    return page["url"]


async def create_note(text: str) -> str:
    data_source_id, schema = await _get_data_source(settings.notion_notes_db_id)
    properties: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": text[:80]}}]},
    }
    if "Content" in schema:
        properties["Content"] = {"rich_text": [{"text": {"content": text[:2000]}}]}
    page = await _client.pages.create(
        parent={"type": "data_source_id", "data_source_id": data_source_id},
        properties=properties,
    )
    return page["url"]


def _read_text(prop: dict[str, Any] | None) -> str:
    """Прочитать текстовое значение независимо от того, каким типом
    свойства пользователь реально завёл поле в Notion (Text/Select/Status/Title)."""
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


def _read_number(prop: dict[str, Any] | None) -> float | None:
    """Как _read_text, но для чисел — на случай, если поле завели как Text."""
    if not prop:
        return None
    if "number" in prop:
        return prop["number"]
    text = _read_text(prop)
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _read_date(prop: dict[str, Any] | None) -> date | None:
    if not prop:
        return None
    raw = prop.get("date")
    return date.fromisoformat(raw["start"][:10]) if raw else None


def parse_diary_page(page: dict[str, Any]) -> dict[str, Any]:
    props = page["properties"]
    return {
        "notion_page_id": page["id"],
        "entry_date": _read_date(props.get("Date")),
        "physical": _read_number(props.get("Physical")),
        "social": _read_number(props.get("Social")),
        "productivity": _read_number(props.get("Productivity")),
        "happiness": _read_number(props.get("Happiness")),
        "highlight": _read_text(props.get("Highlight")) or None,
    }


async def list_diary_entries() -> list[dict[str, Any]]:
    """Забрать все записи дневника — без серверной фильтрации по дате
    (датасет маленький, фильтруем на своей стороне)."""
    data_source_id, _ = await _get_data_source(settings.notion_diary_db_id)
    entries: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"data_source_id": data_source_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = await _client.data_sources.query(**kwargs)
        entries.extend(parse_diary_page(page) for page in response["results"])
        if not response.get("has_more"):
            break
        cursor = response["next_cursor"]
    return entries
