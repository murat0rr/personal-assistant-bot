from datetime import date

from src.integrations.notion import _build_task_properties

_FULL_SELECT_SCHEMA = {
    "Name": {"type": "title"},
    "Due date": {"type": "date"},
    "Priority": {"type": "select"},
    "Status": {"type": "select"},
    "Source": {"type": "rich_text"},
}

_NATIVE_STATUS_SCHEMA = {
    "Name": {"type": "title"},
    "Due date": {"type": "date"},
    "Priority": {"type": "select"},
    "Status": {
        "type": "status",
        "status": {
            "options": [
                {"name": "Not started"},
                {"name": "In progress"},
                {"name": "Done"},
            ]
        },
    },
    # без Source — типичный случай, когда пользователь не добавил колонку
}


def test_build_task_properties_with_select_status_and_source():
    props = _build_task_properties(
        "купить хлеб", date(2026, 8, 29), "высокий", "F1", _FULL_SELECT_SCHEMA
    )

    assert props["Name"] == {"title": [{"text": {"content": "купить хлеб"}}]}
    assert props["Priority"] == {"select": {"name": "высокий"}}
    assert props["Status"] == {"select": {"name": "to-do"}}
    assert props["Source"] == {"rich_text": [{"text": {"content": "F1"}}]}
    assert props["Due date"] == {"date": {"start": "2026-08-29"}}


def test_build_task_properties_native_status_and_missing_source():
    props = _build_task_properties("позвонить маме", None, "средний", "F1", _NATIVE_STATUS_SCHEMA)

    assert props["Status"] == {"status": {"name": "Not started"}}
    assert "Source" not in props
    assert "Due date" not in props


def test_build_task_properties_date_property_named_date():
    # Реальный случай: база использует "Date", а не "Due date".
    schema = {
        "Name": {"type": "title"},
        "Date": {"type": "date"},
        "Priority": {"type": "select"},
        "Status": {"type": "select"},
    }
    props = _build_task_properties("купить хлеб", date(2026, 8, 29), "высокий", "F1", schema)

    assert props["Date"] == {"date": {"start": "2026-08-29"}}
    assert "Due date" not in props
