from datetime import datetime

from fastapi.testclient import TestClient

from src.adapters.api import _parse_due_date, app


def test_parse_due_date_plain_date_goes_to_midnight():
    assert _parse_due_date("2026-09-01") == datetime(2026, 9, 1, 0, 0)


def test_parse_due_date_datetime_local_keeps_time():
    assert _parse_due_date("2026-09-01T14:30") == datetime(2026, 9, 1, 14, 30)


def test_miniapp_response_disables_caching():
    # Telegram WebView кэширует статику Mini App заметно агрессивнее
    # обычного браузера (официальная рекомендация docs.ton.org для TMA —
    # см. _no_cache_miniapp в api.py) — без этих заголовков после деплоя
    # пользователь может продолжать видеть старую версию сколько угодно
    # долго, пока вручную не очистит кэш приложения.
    client = TestClient(app)
    response = client.get("/miniapp/")
    assert response.headers["cache-control"] == "no-store, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
