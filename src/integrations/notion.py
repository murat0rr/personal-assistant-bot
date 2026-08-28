from datetime import date
from typing import Any

from notion_client import AsyncClient

from src.core.config import settings

_client = AsyncClient(auth=settings.notion_api_key)

_NEW_TASK_STATUS_CANDIDATES = ("to-do", "to do", "not started")


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

    if "Due date" in schema and due_date is not None:
        properties["Due date"] = {"date": {"start": due_date.isoformat()}}

    status_prop = schema.get("Status")
    if status_prop is not None:
        if status_prop["type"] == "status":
            options = status_prop["status"]["options"]
            option_name = next(
                (o["name"] for o in options if o["name"].lower() in _NEW_TASK_STATUS_CANDIDATES),
                options[0]["name"] if options else "Not started",
            )
            properties["Status"] = {"status": {"name": option_name}}
        else:
            properties["Status"] = {"select": {"name": "to-do"}}

    if "Source" in schema:
        properties["Source"] = {"rich_text": [{"text": {"content": source}}]}

    return properties


async def create_task(
    title: str,
    due_date: date | None,
    priority: str,
    source: str = "F1",
) -> str:
    db = await _client.databases.retrieve(database_id=settings.notion_tasks_db_id)
    data_source_id = db["data_sources"][0]["id"]
    data_source = await _client.data_sources.retrieve(data_source_id=data_source_id)
    properties = _build_task_properties(
        title, due_date, priority, source, data_source["properties"]
    )
    page = await _client.pages.create(
        parent={"type": "data_source_id", "data_source_id": data_source_id},
        properties=properties,
    )
    return page["url"]
