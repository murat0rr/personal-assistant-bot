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


# ---- Вход в веб-версию вне Telegram (Phase 45) — /app, /auth/* без
# похода в БД/Bot API там, где это возможно (см. api.py::web_app_entry,
# web_auth.py). Код в чате с ботом (не Telegram Login Widget — тот
# упёрся в недоставку кода подтверждения силами самого Telegram, вне
# нашего контроля, см. SPEC.md Phase 45).


def test_app_route_redirects_to_login_without_session_cookie():
    client = TestClient(app, follow_redirects=False)
    response = client.get("/app/")
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/auth/login"


def test_app_route_also_no_caches():
    client = TestClient(app, follow_redirects=False)
    response = client.get("/app/")
    assert response.headers["cache-control"] == "no-store, must-revalidate"


def test_login_page_renders_code_form():
    client = TestClient(app)
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert "/webcode" in response.text
    assert 'name="code"' in response.text


def test_verify_code_rejects_unknown_code_without_db():
    # verify_code — чистый dict-lookup (src/core/login_codes.py), без
    # похода в БД, поэтому проверяемо без реального authorized_users.
    client = TestClient(app)
    response = client.post("/auth/verify-code", data={"code": "0000"})
    assert response.status_code == 200
    assert "неверный" in response.text.lower()


def test_verify_code_rate_limited_after_too_many_attempts():
    from src.core import login_codes

    login_codes._VERIFY_ATTEMPTS_BY_IP.clear()
    client = TestClient(app)
    for _ in range(login_codes._MAX_VERIFY_ATTEMPTS_PER_IP):
        client.post("/auth/verify-code", data={"code": "0000"})
    response = client.post("/auth/verify-code", data={"code": "0000"})
    assert "слишком много попыток" in response.text.lower()
    login_codes._VERIFY_ATTEMPTS_BY_IP.clear()
