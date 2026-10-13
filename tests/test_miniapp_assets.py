from pathlib import Path

import pytest

from src.adapters import miniapp_assets


@pytest.fixture(autouse=True)
def _reset_version_cache():
    """get_asset_version кеширует результат в module-level переменной
    (см. miniapp_assets.py — она не меняется, пока не пересоздан
    контейнер) — в тестах это нужно сбрасывать между кейсами, иначе
    второй вызов с другой tmp_path всё равно вернёт версию от первого."""
    miniapp_assets._asset_version_cache = None
    yield
    miniapp_assets._asset_version_cache = None


def _make_static_dir(
    tmp_path: Path, css_content: str = "body{}", js_content: str = "export {};"
) -> Path:
    (tmp_path / "css").mkdir(parents=True)
    (tmp_path / "css" / "app.css").write_text(css_content, encoding="utf-8")
    (tmp_path / "js").mkdir(parents=True)
    (tmp_path / "js" / "core.js").write_text(js_content, encoding="utf-8")
    return tmp_path


def test_version_rewrites_absolute_css_ref():
    html = '<link rel="stylesheet" href="/miniapp/css/app.css">'
    result = miniapp_assets.version_asset_refs(html, "abc123")
    assert result == '<link rel="stylesheet" href="/miniapp/css/app.css?v=abc123">'


def test_version_rewrites_absolute_js_ref():
    html = '<script src="/miniapp/js/core/icons.js"></script>'
    result = miniapp_assets.version_asset_refs(html, "abc123")
    assert result == '<script src="/miniapp/js/core/icons.js?v=abc123"></script>'


def test_version_rewrites_relative_js_import():
    js = 'import { WIDGET_REGISTRY } from "./registry.js";'
    result = miniapp_assets.version_asset_refs(js, "abc123")
    assert result == 'import { WIDGET_REGISTRY } from "./registry.js?v=abc123";'


def test_version_rewrites_relative_js_import_single_quotes():
    js = "import { bus } from './bus.js';"
    result = miniapp_assets.version_asset_refs(js, "abc123")
    assert result == "import { bus } from './bus.js?v=abc123';"


def test_version_rewrites_nested_absolute_js_path():
    html = 'import { bus } from "/miniapp/js/core/bus.js";'
    result = miniapp_assets.version_asset_refs(html, "abc123")
    assert result == 'import { bus } from "/miniapp/js/core/bus.js?v=abc123";'


def test_version_leaves_manifest_untouched():
    html = '<link rel="manifest" href="/miniapp/manifest.json">'
    assert miniapp_assets.version_asset_refs(html, "abc123") == html


def test_version_leaves_icons_untouched():
    html = '<link rel="icon" href="/miniapp/icons/favicon-32.png">'
    assert miniapp_assets.version_asset_refs(html, "abc123") == html


def test_version_leaves_service_worker_untouched():
    js = 'navigator.serviceWorker.register("/miniapp/service-worker.js").catch(() => {});'
    assert miniapp_assets.version_asset_refs(js, "abc123") == js


def test_version_leaves_api_calls_untouched():
    js = 'boardState = await api("/miniapp/api/tasks");'
    assert miniapp_assets.version_asset_refs(js, "abc123") == js


def test_version_rewrites_multiple_refs_in_one_document():
    html = (
        '<link rel="stylesheet" href="/miniapp/css/app.css">\n'
        '<script src="/miniapp/js/core/icons.js"></script>'
    )
    result = miniapp_assets.version_asset_refs(html, "v1")
    assert "app.css?v=v1" in result
    assert "icons.js?v=v1" in result


def test_asset_version_is_deterministic_for_same_content(tmp_path):
    static_dir = _make_static_dir(tmp_path)
    version_a = miniapp_assets.get_asset_version(static_dir)
    # Второй вызов должен попасть в кэш и вернуть то же самое, не
    # пересчитывать — но для теста это и есть ожидаемое поведение.
    version_b = miniapp_assets.get_asset_version(static_dir)
    assert version_a == version_b
    assert len(version_a) == 12


def test_asset_version_changes_when_css_content_changes(tmp_path):
    dir_a = _make_static_dir(tmp_path / "a", css_content="body{color:red}")
    version_a = miniapp_assets.get_asset_version(dir_a)

    miniapp_assets._asset_version_cache = None

    dir_b = _make_static_dir(tmp_path / "b", css_content="body{color:blue}")
    version_b = miniapp_assets.get_asset_version(dir_b)

    assert version_a != version_b


def test_asset_version_changes_when_js_content_changes(tmp_path):
    dir_a = _make_static_dir(tmp_path / "a", js_content="export const x = 1;")
    version_a = miniapp_assets.get_asset_version(dir_a)

    miniapp_assets._asset_version_cache = None

    dir_b = _make_static_dir(tmp_path / "b", js_content="export const x = 2;")
    version_b = miniapp_assets.get_asset_version(dir_b)

    assert version_a != version_b


def test_asset_version_stable_when_content_unchanged(tmp_path):
    dir_a = _make_static_dir(tmp_path / "a")
    version_a = miniapp_assets.get_asset_version(dir_a)

    miniapp_assets._asset_version_cache = None

    dir_b = _make_static_dir(tmp_path / "b")  # тот же контент, другая директория
    version_b = miniapp_assets.get_asset_version(dir_b)

    assert version_a == version_b
