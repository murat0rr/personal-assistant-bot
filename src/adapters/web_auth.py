"""Вход в веб-версию приложения (/app/) вне Telegram-клиента (Phase 45,
вторая переделка — см. src/core/login_codes.py за полной историей).

Финальный поток: человек сам пишет боту /webcode (src/handlers/
f_web_login.py) — бот тут же знает его user_id из входящего сообщения,
без всякого резолвинга через Bot API, и присылает 4-значный код тем же
sendMessage, что и все остальные уведомления в проекте. Сайт просит
только этот код — ни username, ни номер телефона, ни сторонний OAuth-
попап (первая версия на Telegram Login Widget упёрлась именно в
недоставку кода со стороны Telegram, вне нашего контроля — см. SPEC.md
Phase 45)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.login_codes import can_attempt_verify, record_verify_attempt, verify_code
from src.core.web_session import SESSION_COOKIE_NAME, create_session_token

router = APIRouter(prefix="/auth")

_PAGE_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f2f2f2; color: #111; display: flex; align-items: center;
    justify-content: center; min-height: 100vh; margin: 0; padding: 24px;
    box-sizing: border-box; text-align: center; }
  .card { max-width: 320px; width: 100%; }
  h1 { font-size: 18px; margin: 0 0 12px; }
  p { color: #666; font-size: 14px; line-height: 1.5; margin: 0 0 16px; }
  input { width: 100%; box-sizing: border-box; padding: 12px 14px; font-size: 16px;
    border: 1px solid #ddd; border-radius: 10px; margin-bottom: 12px; text-align: center;
    letter-spacing: 4px; }
  button { width: 100%; padding: 12px 14px; font-size: 16px; border: none;
    border-radius: 10px; background: #2481cc; color: #fff; font-weight: 600; }
  a { color: #2481cc; }
</style>
"""


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head>{_PAGE_STYLE}</head><body>{body}</body></html>"
    )


_NOT_CONFIGURED_PAGE = """
<div class="card"><h1>Вход не настроен</h1>
<p>Веб-версия вне Telegram недоступна — обратитесь к владельцу бота.</p></div>
"""


@router.get("/login")
async def login_page() -> HTMLResponse:
    # SESSION_SECRET не задан — фича опциональна (см. Settings.session_secret),
    # но тогда должна быть выключена целиком, а не тихо подписывать
    # HMAC пустым ключом (Phase 58, БАГ безопасности).
    if not settings.session_secret:
        return _page(_NOT_CONFIGURED_PAGE)
    bot_hint = f" @{settings.telegram_bot_username}" if settings.telegram_bot_username else ""
    return _page(f"""
    <div class="card">
      <h1>Личный ассистент</h1>
      <p>Напишите боту{bot_hint} команду <b>/webcode</b> в Telegram —
      он пришлёт код подтверждения. Введите его здесь, чтобы открыть
      приложение в браузере.</p>
      <form method="post" action="/auth/verify-code">
        <input name="code" placeholder="0000" maxlength="4" inputmode="numeric"
          autocomplete="off" required>
        <button type="submit">Войти</button>
      </form>
    </div>
    """)


@router.post("/verify-code", response_model=None)
async def verify_code_endpoint(request: Request) -> HTMLResponse | RedirectResponse:
    # Тот же guard, что и у GET /login (Phase 58) — прямой POST мимо
    # страницы входа не должен обойти проверку "фича выключена".
    if not settings.session_secret:
        return _page(_NOT_CONFIGURED_PAGE)
    client_ip = request.client.host if request.client else "unknown"
    if not await can_attempt_verify(client_ip):
        return _page("""
        <div class="card"><h1>Слишком много попыток</h1>
        <p>Подождите немного и запросите новый код через /webcode.</p>
        <p><a href="/auth/login">← Назад</a></p></div>
        """)
    await record_verify_attempt(client_ip)

    form = await request.form()
    code = str(form.get("code", "")).strip()

    user_id = await verify_code(code)
    # Дополнительно к самому существованию кода — тот же контур
    # авторизации, что и у Mini App: код мог быть выписан пользователю,
    # которого затем убрали из authorized_users (маловероятно, но
    # дёшево перепроверить).
    if user_id is None or not await is_authorized(user_id):
        return _page("""
        <div class="card"><h1>Неверный или истёкший код</h1>
        <p>Запросите новый код командой /webcode в Telegram.</p>
        <p><a href="/auth/login">← Назад</a></p></div>
        """)

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
