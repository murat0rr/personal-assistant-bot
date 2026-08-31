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


# ---- Вход в веб-версию вне Telegram (Phase 45) — /app и /auth/login без
# похода в БД (короткое замыкание на "нет куки"/"не настроено" не требует
# запроса к authorized_users, см. api.py::web_app_entry и
# web_auth.py::login_page).


def test_app_route_redirects_to_login_without_session_cookie():
    client = TestClient(app, follow_redirects=False)
    response = client.get("/app/")
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/auth/login"


def test_app_route_also_no_caches():
    client = TestClient(app, follow_redirects=False)
    response = client.get("/app/")
    assert response.headers["cache-control"] == "no-store, must-revalidate"


def test_login_page_degrades_when_not_configured():
    # session_secret/telegram_bot_username пустые по умолчанию (не заданы
    # в .env этой тестовой среды) — /auth/login должен объяснить, что не
    # так, а не 500 или пустая страница.
    client = TestClient(app)
    response = client.get("/auth/login")
    assert response.status_code == 503
    assert "не настроен" in response.text.lower()
