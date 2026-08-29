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


def _is_archived(task_status: str) -> bool:
    """TaskStatus может быть multi_select (несколько тегов через запятую) —
    проверяем членство "archived" среди тегов, а не точное равенство."""
    tags = {tag.strip().lower() for tag in task_status.split(",")}
    return "archived" in tags


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

    task_status = _read_text(props.get("TaskStatus"))

    return {
        "notion_page_id": page["id"],
        "title": title,
        "due_date": due_date,
        "priority": priority,
        "status": status,
        "source": source,
        "task_status": task_status,
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
) -> tuple[str, str]:
    """Возвращает (notion_page_id, url) — page_id нужен вызывающему коду,
    чтобы завести соответствующую строку в локальном Postgres-кэше."""
    data_source_id, schema = await _get_data_source(settings.notion_tasks_db_id)
    properties = _build_task_properties(title, due_date, priority, source, schema)
    page = await _client.pages.create(
        parent={"type": "data_source_id", "data_source_id": data_source_id},
        properties=properties,
    )
    return page["id"], page["url"]


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
    есть в схеме базы — тот же адаптивный паттерн, что у create_task."""
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


async def archive_task(page_id: str) -> None:
    """Мягкое удаление — не архивирует саму страницу Notion, а проставляет
    свойству TaskStatus значение "archived" (кнопка "корзина" в Mini App).
    Требует, чтобы в базе Tasks было заведено свойство с именем ровно
    "TaskStatus" (Select или Status) — если его нет, явно сообщаем об этом,
    а не создаём свойство втихую."""
    _, schema = await _get_data_source(settings.notion_tasks_db_id)
    task_status_schema = schema.get("TaskStatus")
    if task_status_schema is None:
        raise ValueError(
            'В базе Notion Tasks нет свойства "TaskStatus" — добавь его '
            '(Select или Status) с опцией "archived".'
        )
    value = _write_text_property(task_status_schema, "archived")
    await _client.pages.update(page_id=page_id, properties={"TaskStatus": value})


async def update_task_due_date(page_id: str, due_date: date) -> None:
    _, schema = await _get_data_source(settings.notion_tasks_db_id)
    date_property = _find_date_property(schema)
    if date_property is None:
        return
    await _client.pages.update(
        page_id=page_id,
        properties={date_property: {"date": {"start": due_date.isoformat()}}},
    )


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


def _write_text_property(prop_schema: dict[str, Any], value: str) -> dict[str, Any]:
    """Как _write_number, но для текстовых значений — под фактический тип
    свойства (Select/Status/Multi-select/Text)."""
    prop_type = prop_schema["type"]
    if prop_type == "status":
        return {"status": {"name": value}}
    if prop_type == "select":
        return {"select": {"name": value}}
    if prop_type == "multi_select":
        return {"multi_select": [{"name": value}]}
    return {"rich_text": [{"text": {"content": value}}]}


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


def _write_number(prop_schema: dict[str, Any], value: float) -> dict[str, Any]:
    if prop_schema["type"] == "number":
        return {"number": value}
    return {"rich_text": [{"text": {"content": str(value)}}]}


def parse_habit_page(page: dict[str, Any]) -> dict[str, Any]:
    props = page["properties"]
    return {
        "notion_page_id": page["id"],
        "name": _read_text(props.get("Name")) or "(без названия)",
        "streak": int(_read_number(props.get("Streak")) or 0),
        "last_checked": _read_date(props.get("Last checked")),
        "target_frequency": _read_text(props.get("Target frequency")) or "daily",
    }


async def list_habits() -> list[dict[str, Any]]:
    data_source_id, _ = await _get_data_source(settings.notion_habits_db_id)
    habits: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"data_source_id": data_source_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = await _client.data_sources.query(**kwargs)
        habits.extend(parse_habit_page(page) for page in response["results"])
        if not response.get("has_more"):
            break
        cursor = response["next_cursor"]
    return habits


async def get_habit(page_id: str) -> dict[str, Any]:
    page = await _client.pages.retrieve(page_id=page_id)
    return parse_habit_page(page)


async def update_habit_check(page_id: str, new_streak: int, checked_on: date) -> None:
    _, schema = await _get_data_source(settings.notion_habits_db_id)
    properties: dict[str, Any] = {
        "Last checked": {"date": {"start": checked_on.isoformat()}},
    }
    streak_schema = schema.get("Streak")
    if streak_schema is not None:
        properties["Streak"] = _write_number(streak_schema, new_streak)
    await _client.pages.update(page_id=page_id, properties=properties)


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
    (датасет маленький, фильтруем на своей стороне), тот же паттерн, что
    list_habits."""
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


async def list_tasks() -> list[dict[str, Any]]:
    """Забрать все задачи из Notion Tasks — используется pull-синком
    (плановым и по требованию), а не входящими вебхуками. Задачи с
    TaskStatus="archived" (см. archive_task) сюда не попадают — это и есть
    "корзина" в Mini App."""
    data_source_id, _ = await _get_data_source(settings.notion_tasks_db_id)

    tasks: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"data_source_id": data_source_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = await _client.data_sources.query(**kwargs)
        for page in response["results"]:
            parsed = parse_task_page(page)
            if not _is_archived(parsed["task_status"]):
                tasks.append(parsed)
        if not response.get("has_more"):
            break
        cursor = response["next_cursor"]

    return tasks
