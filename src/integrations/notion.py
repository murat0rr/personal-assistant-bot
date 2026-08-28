from datetime import date
from typing import Any

from notion_client import AsyncClient

from src.core.config import settings

_client = AsyncClient(auth=settings.notion_api_key)

_NEW_TASK_STATUS_CANDIDATES = ("to-do", "to do", "not started")
DONE_STATUS_CANDIDATES = ("done", "complete", "completed")
# Название свойства с датой срока варьируется от базы к базе (в реальной
# базе оказалось "Date", а не "Due date", как в первоначальной инструкции).
_DATE_PROPERTY_CANDIDATES = ("Due date", "Date")


def _find_date_property(schema: dict[str, Any]) -> str | None:
    return next((name for name in _DATE_PROPERTY_CANDIDATES if name in schema), None)


def _resolve_status_value(
    status_prop: dict[str, Any], candidates: tuple[str, ...], fallback_index: int
) -> dict[str, Any]:
    """Собрать значение properties["Status"] под фактический тип свойства
    (нативный Notion "status" с произвольными опциями, либо обычный "select")."""
    if status_prop["type"] == "status":
        options = status_prop["status"]["options"]
        option_name = next(
            (o["name"] for o in options if o["name"].lower() in candidates),
            options[fallback_index]["name"] if options else candidates[0],
        )
        return {"status": {"name": option_name}}
    return {"select": {"name": candidates[0]}}


def _build_task_properties(
    title: str,
    due_date: date | None,
    priority: str,
    source: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Собрать properties под фактическую схему базы (а не жёстко заданную)."""
    properties: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": title}}]},
    }

    if "Priority" in schema:
        properties["Priority"] = {"select": {"name": priority}}

    date_property = _find_date_property(schema)
    if date_property is not None and due_date is not None:
        properties[date_property] = {"date": {"start": due_date.isoformat()}}

    status_prop = schema.get("Status")
    if status_prop is not None:
        properties["Status"] = _resolve_status_value(status_prop, _NEW_TASK_STATUS_CANDIDATES, 0)

    if "Source" in schema:
        properties["Source"] = {"rich_text": [{"text": {"content": source}}]}

    return properties


def parse_task_page(page: dict[str, Any]) -> dict[str, Any]:
    """Распарсить страницу Notion в плоский словарь для кэша в Postgres."""
    props = page["properties"]

    title_parts = props.get("Name", {}).get("title", [])
    title = "".join(part["plain_text"] for part in title_parts) or "(без названия)"

    due = props.get("Due date", {}).get("date") or props.get("Date", {}).get("date")
    due_date = date.fromisoformat(due["start"][:10]) if due else None

    priority_prop = props.get("Priority", {}).get("select")
    priority = priority_prop["name"] if priority_prop else None

    status_field = props.get("Status", {})
    status_value = status_field.get("status") or status_field.get("select")
    status = status_value["name"] if status_value else "unknown"

    source_parts = props.get("Source", {}).get("rich_text", [])
    source = "".join(part["plain_text"] for part in source_parts) or None

    return {
        "notion_page_id": page["id"],
        "title": title,
        "due_date": due_date,
        "priority": priority,
        "status": status,
        "source": source,
    }


async def _get_data_source(database_id: str) -> tuple[str, dict[str, Any]]:
    db = await _client.databases.retrieve(database_id=database_id)
    data_source_id = db["data_sources"][0]["id"]
    data_source = await _client.data_sources.retrieve(data_source_id=data_source_id)
    return data_source_id, data_source["properties"]


async def create_task(
    title: str,
    due_date: date | None,
    priority: str,
    source: str = "F1",
) -> str:
    data_source_id, schema = await _get_data_source(settings.notion_tasks_db_id)
    properties = _build_task_properties(title, due_date, priority, source, schema)
    page = await _client.pages.create(
        parent={"type": "data_source_id", "data_source_id": data_source_id},
        properties=properties,
    )
    return page["url"]


async def create_diary_entry(entry_date: date, answers_text: str, summary_text: str) -> str:
    """Записать вечерний дневник. Поля заполняются, только если реально
    есть в схеме базы — тот же адаптивный паттерн, что у create_task."""
    data_source_id, schema = await _get_data_source(settings.notion_diary_db_id)
    properties: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": entry_date.isoformat()}}]},
    }
    if "Date" in schema:
        properties["Date"] = {"date": {"start": entry_date.isoformat()}}
    if "Answers" in schema:
        properties["Answers"] = {"rich_text": [{"text": {"content": answers_text[:2000]}}]}
    if "Summary" in schema:
        properties["Summary"] = {"rich_text": [{"text": {"content": summary_text[:2000]}}]}
    page = await _client.pages.create(
        parent={"type": "data_source_id", "data_source_id": data_source_id},
        properties=properties,
    )
    return page["url"]


async def update_task_status(page_id: str, done: bool) -> str:
    """Обновить статус задачи в Notion. Возвращает реально записанную метку
    статуса — её же нужно сохранить в Postgres, чтобы не словить дублирующее
    уведомление, когда следом прилетит вебхук об этом же изменении."""
    _, schema = await _get_data_source(settings.notion_tasks_db_id)
    status_prop = schema.get("Status")
    if status_prop is None:
        return "unknown"
    candidates = DONE_STATUS_CANDIDATES if done else _NEW_TASK_STATUS_CANDIDATES
    fallback_index = -1 if done else 0
    value = _resolve_status_value(status_prop, candidates, fallback_index)
    await _client.pages.update(page_id=page_id, properties={"Status": value})
    return value["status"]["name"] if "status" in value else value["select"]["name"]


async def list_tasks() -> list[dict[str, Any]]:
    """Забрать все задачи из Notion Tasks — используется pull-синком
    (плановым и по требованию), а не входящими вебхуками."""
    data_source_id, _ = await _get_data_source(settings.notion_tasks_db_id)

    tasks: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"data_source_id": data_source_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = await _client.data_sources.query(**kwargs)
        tasks.extend(parse_task_page(page) for page in response["results"])
        if not response.get("has_more"):
            break
        cursor = response["next_cursor"]

    return tasks
