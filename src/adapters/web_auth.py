"""Вход в веб-версию приложения (/app/) вне Telegram-клиента через
Telegram Login Widget (Phase 45). Самостоятельная регистрация НЕ
вводится — входить может только тот, кто уже есть в authorized_users
(тот же пароль-гейт F14, что и у бота); чужой Telegram-аккаунт видит
понятный отказ, сессия не выставляется."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.telegram_auth import verify_telegram_login_widget_data
from src.core.web_session import SESSION_COOKIE_NAME, create_session_token

router = APIRouter(prefix="/auth")

_PAGE_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f2f2f2; color: #111; display: flex; align-items: center;
    justify-content: center; min-height: 100vh; margin: 0; padding: 24px;
    box-sizing: border-box; text-align: center; }
  .card { max-width: 320px; }
  h1 { font-size: 18px; margin: 0 0 12px; }
  p { color: #666; font-size: 14px; line-height: 1.5; }
</style>
"""


@router.get("/login")
async def login_page(request: Request) -> HTMLResponse:
    if not settings.telegram_bot_username or not settings.session_secret:
        # Та же деградация, что у /staging без STAGING_MINIAPP_URL — не
        # 500, а понятный текст: секрет/username бота ещё не заведены в
        # .env на этом окружении.
        return HTMLResponse(
            f"<!doctype html><html><head>{_PAGE_STYLE}</head><body>"
            '<div class="card"><h1>Вход не настроен</h1>'
            "<p>TELEGRAM_BOT_USERNAME/SESSION_SECRET не заданы в .env "
            "на этом сервере.</p></div></body></html>",
            status_code=503,
        )
    # Абсолютный URL нужен виджету (data-auth-url), а base_url самого
    # запроса — уже готовая схема+домен, без отдельной настройки и без
    # риска разойтись с тем, на каком домене реально открыли /auth/login
    # (staging и прод могут отличаться).
    callback_url = str(request.base_url).rstrip("/") + "/auth/telegram/callback"
    return HTMLResponse(f"""<!doctype html>
<html>
<head>{_PAGE_STYLE}</head>
<body>
  <div class="card">
    <h1>Личный ассистент</h1>
    <p>Войдите через Telegram, чтобы открыть приложение в браузере.</p>
    <script async src="https://telegram.org/js/telegram-widget.js?22"
      data-telegram-login="{settings.telegram_bot_username}"
      data-size="large"
      data-auth-url="{callback_url}"
      data-request-access="write"></script>
  </div>
</body>
</html>""")


@router.get("/telegram/callback", response_model=None)
async def telegram_callback(request: Request) -> HTMLResponse | RedirectResponse:
    data = dict(request.query_params)
    verified = verify_telegram_login_widget_data(data, settings.telegram_bot_token)
    if verified is None:
        return HTMLResponse(
            f"<!doctype html><html><head>{_PAGE_STYLE}</head><body>"
            '<div class="card"><h1>Не удалось войти</h1>'
            "<p>Подпись Telegram не прошла проверку — попробуйте войти "
            "заново.</p></div></body></html>",
            status_code=400,
        )

    user_id = int(verified["id"])
    if not await is_authorized(user_id):
        return HTMLResponse(
            f"<!doctype html><html><head>{_PAGE_STYLE}</head><body>"
            '<div class="card"><h1>Нет доступа</h1>'
            "<p>Этот Telegram-аккаунт не авторизован в приложении. "
            "Обратитесь к владельцу.</p></div></body></html>",
            status_code=403,
        )

    response = RedirectResponse(url="/app/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user_id),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,
    )
    return response


@router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
