from datetime import date

from src.integrations.notion import _resolve_status_value, parse_task_page

_NATIVE_STATUS_SCHEMA = {
    "type": "status",
    "status": {
        "options": [
            {"name": "Not started"},
            {"name": "In progress"},
            {"name": "Done"},
        ]
    },
}

_SELECT_STATUS_SCHEMA = {"type": "select"}


def test_resolve_status_value_native_done_picks_last_matching_option():
    value = _resolve_status_value(_NATIVE_STATUS_SCHEMA, ("done", "complete"), -1)
    assert value == {"status": {"name": "Done"}}


def test_resolve_status_value_select_done():
    value = _resolve_status_value(_SELECT_STATUS_SCHEMA, ("done", "complete"), -1)
    assert value == {"select": {"name": "done"}}


def test_parse_task_page_full():
    page = {
        "id": "abc123",
        "properties": {
            "Name": {"title": [{"plain_text": "купить хлеб"}]},
            "Due date": {"date": {"start": "2026-08-29"}},
            "Priority": {"select": {"name": "высокий"}},
            "Status": {"status": {"name": "Done"}},
            "Source": {"rich_text": [{"plain_text": "F1"}]},
        },
    }

    parsed = parse_task_page(page)

    assert parsed == {
        "notion_page_id": "abc123",
        "title": "купить хлеб",
        "due_date": date(2026, 8, 29),
        "priority": "высокий",
        "status": "Done",
        "source": "F1",
    }


def test_parse_task_page_date_property_named_date():
    # Реальный случай: база использует "Date", а не "Due date".
    page = {
        "id": "abc123",
        "properties": {
            "Name": {"title": [{"plain_text": "купить хлеб"}]},
            "Date": {"date": {"start": "2026-08-29"}},
            "Status": {"select": {"name": "to-do"}},
        },
    }

    parsed = parse_task_page(page)

    assert parsed["due_date"] == date(2026, 8, 29)


def test_parse_task_page_minimal():
    page = {
        "id": "xyz",
        "properties": {
            "Name": {"title": [{"plain_text": "позвонить маме"}]},
            "Status": {"select": {"name": "to-do"}},
        },
    }

    parsed = parse_task_page(page)

    assert parsed["due_date"] is None
    assert parsed["priority"] is None
    assert parsed["source"] is None
    assert parsed["status"] == "to-do"
