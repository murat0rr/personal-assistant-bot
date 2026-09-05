"""OAuth-коллбэк подключения Google Calendar (Phase 64) — редирект от
Google после согласия пользователя, не Telegram-контекст (см.
handlers/f_google_calendar.py за тем, как строится ссылка на согласие,
core/google_oauth_state.py за проверкой state)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.core.config import settings
from src.core.db import async_session
from src.core.google_oauth_state import consume_state
from src.integrations.google_calendar import exchange_code
from src.models.google_calendar_account import GoogleCalendarAccount

router = APIRouter(prefix="/google")

_PAGE_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f2f2f2; color: #111; display: flex; align-items: center;
    justify-content: center; min-height: 100vh; margin: 0; padding: 24px;
    box-sizing: border-box; text-align: center; }
  .card { max-width: 320px; width: 100%; }
  h1 { font-size: 18px; margin: 0 0 12px; }
  p { color: #666; font-size: 14px; line-height: 1.5; margin: 0; }
</style>
"""


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head>{_PAGE_STYLE}</head><body>{body}</body></html>"
    )


@router.get("/oauth/callback")
async def oauth_callback(request: Request) -> HTMLResponse:
    if not settings.google_client_id:
        return _page("<div class='card'><h1>Не настроено</h1></div>")

    params = request.query_params
    if params.get("error"):
        return _page(
            "<div class='card'><h1>Доступ не предоставлен</h1>"
            "<p>Можно закрыть вкладку и повторить командой /google_calendar в боте.</p></div>"
        )

    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        return _page("<div class='card'><h1>Некорректный запрос</h1></div>")

    user_id = await consume_state(state)
    if user_id is None:
        return _page(
            "<div class='card'><h1>Ссылка устарела</h1>"
            "<p>Запросите новую командой /google_calendar в боте.</p></div>"
        )

    try:
        tokens = await exchange_code(code)
        refresh_token = tokens.get("refresh_token")
    except Exception:
        refresh_token = None

    if not refresh_token:
        # Google не отдаёт refresh_token, если пользователь уже когда-то
        # соглашался этому приложению БЕЗ prompt=consent — у нас он всегда
        # передаётся (см. build_auth_url), так что это реальный сбой
        # обмена, а не штатный повторный вход.
        return _page(
            "<div class='card'><h1>Не удалось подключить</h1>"
            "<p>Попробуйте ещё раз командой /google_calendar в боте.</p></div>"
        )

    async with async_session() as session:
        existing = await session.get(GoogleCalendarAccount, user_id)
        if existing is None:
            session.add(GoogleCalendarAccount(user_id=user_id, refresh_token=refresh_token))
        else:
            existing.refresh_token = refresh_token
        await session.commit()

    return _page(
        "<div class='card'><h1>Google Calendar подключён</h1>"
        "<p>Можно закрыть вкладку — события начнут появляться в задачах "
        "в течение ближайших минут.</p></div>"
    )
