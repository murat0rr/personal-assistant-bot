from src.integrations.notion import _read_text


def test_read_text_supports_native_status_type():
    prop = {"type": "status", "status": {"name": "archived"}}
    assert _read_text(prop) == "archived"


def test_read_text_missing_property_is_empty():
    assert _read_text(None) == ""
    assert _read_text({}) == ""


def test_read_text_supports_multi_select():
    prop = {"multi_select": [{"name": "urgent"}, {"name": "archived"}]}
    assert _read_text(prop) == "urgent, archived"
