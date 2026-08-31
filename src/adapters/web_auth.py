"""Вход в веб-версию приложения (/app/) вне Telegram-клиента (Phase 45).

Переделано с Telegram Login Widget на код в чате с ботом — виджет
успешно проходил проверку домена, но сама доставка кода подтверждения
номера телефона зависела целиком от Telegram (SMS/сообщение "Telegram"
в приложении) и оказалась ненадёжной вне нашего контроля (живая
проверка — код у пользователя не приходил, даже с активной сессией
Telegram Web). Новая схема надёжнее ровно потому, что использует
единственный канал доставки, который мы уже полностью контролируем и
которым весь проект и так живёт — sendMessage самого бота:

1. Человек вводит свой Telegram-username на /auth/login.
2. Бэкенд ищет чат с этим username через Bot API (getChat) — работает,
   только если бот уже когда-то видел этого человека (тот самый
   пароль-гейт F14: любой авторизованный уже писал боту /start).
3. Если username не резолвится ИЛИ resolved user_id не в
   authorized_users — единый нейтральный ответ в обоих случаях, чтобы
   нельзя было по разнице в тексте угадывать, кто авторизован.
4. Иначе — 4-значный код (src/core/login_codes.py), бот присылает его
   тем же sendMessage, что и все остальные уведомления в проекте.
5. Человек вводит код на /auth/verify — совпадение выдаёт сессионную
   куку (src/core/web_session.py), как и было."""

import html
import re

from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import is_authorized
from src.core.bot_client import get_bot
from src.core.config import settings
from src.core.login_codes import can_request_code, generate_code, normalize_username, verify_code
from src.core.web_session import SESSION_COOKIE_NAME, create_session_token

router = APIRouter(prefix="/auth")

# Тот же формат, что требует сам Telegram для username (5-32 символа,
# латиница/цифры/подчёркивание) — отсекает мусор ДО похода в Bot API.
# username идёт в HTML (скрытое поле формы, ссылка "Ввести код") — эта
# проверка сама по себе уже исключает HTML-спецсимволы, но интерполяции
# всё равно дополнительно экранируются через html.escape() (defense in
# depth — тот же принцип, что SphereField в api.py: два независимых слоя
# лучше одного, даже если один формально уже всё покрывает).
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{5,32}$")

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
    border: 1px solid #ddd; border-radius: 10px; margin-bottom: 12px; text-align: center; }
  button { width: 100%; padding: 12px 14px; font-size: 16px; border: none;
    border-radius: 10px; background: #2481cc; color: #fff; font-weight: 600; }
  a { color: #2481cc; }
</style>
"""


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head>{_PAGE_STYLE}</head><body>{body}</body></html>"
    )


@router.get("/login")
async def login_page() -> HTMLResponse:
    hint = (
        f" Если ещё не писали боту — сначала напишите /start "
        f"@{settings.telegram_bot_username} в Telegram."
        if settings.telegram_bot_username
        else ""
    )
    return _page(f"""
    <div class="card">
      <h1>Личный ассистент</h1>
      <p>Введите свой Telegram-username — пришлём код подтверждения в чат с ботом.{hint}</p>
      <form method="post" action="/auth/request-code">
        <input name="username" placeholder="@username" autocomplete="off" required>
        <button type="submit">Отправить код</button>
      </form>
    </div>
    """)


@router.post("/request-code", response_model=None)
async def request_code(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    username = normalize_username(str(form.get("username", "")))

    # Единый нейтральный ответ и для "не нашли", и для "не авторизован", и
    # для "неверный формат" — не даём угадать по тексту, чей username
    # вообще существует в authorized_users (см. модульный докстринг).
    _denied = _page("""
    <div class="card">
      <h1>Если всё верно — код уже в пути</h1>
      <p>Если этот username писал боту и авторизован в приложении, код
      подтверждения придёт в чат с ботом в течение минуты. Если код не
      приходит — проверьте написание username или обратитесь к владельцу.</p>
      <p><a href="/auth/login">← Назад</a></p>
    </div>
    """)

    if not username or not _USERNAME_RE.match(username):
        return _denied

    if not can_request_code(username):
        safe_username = html.escape(username)
        return _page(f"""
        <div class="card"><h1>Код уже отправлен</h1>
        <p>Подождите минуту перед повторным запросом — проверьте чат с ботом.</p>
        <p><a href="/auth/verify?u={safe_username}">Ввести код →</a></p></div>
        """)

    try:
        chat = await get_bot().get_chat(f"@{username}")
    except TelegramAPIError:
        return _denied

    user_id = chat.id
    if not await is_authorized(user_id):
        return _denied

    code = generate_code(username, user_id)
    try:
        await get_bot().send_message(
            user_id,
            f"Код для входа в веб-версию: {code}\nДействует 5 минут, никому не сообщайте.",
        )
    except TelegramAPIError:
        # Бот резолвит chat, но не может писать (юзер заблокировал бота
        # и т.п.) — тот же нейтральный ответ, ничего не палим.
        return _denied

    return RedirectResponse(url=f"/auth/verify?u={username}", status_code=303)


@router.get("/verify", response_model=None)
async def verify_page(u: str = "") -> HTMLResponse | RedirectResponse:
    username = normalize_username(u)
    if not username or not _USERNAME_RE.match(username):
        return RedirectResponse(url="/auth/login")
    safe_username = html.escape(username)
    return _page(f"""
    <div class="card">
      <h1>Код из Telegram</h1>
      <p>Введите 4-значный код, который прислал бот.</p>
      <form method="post" action="/auth/verify-code">
        <input type="hidden" name="username" value="{safe_username}">
        <input name="code" placeholder="0000" maxlength="4" inputmode="numeric"
          autocomplete="off" required>
        <button type="submit">Войти</button>
      </form>
      <p><a href="/auth/login">← Ввести другой username</a></p>
    </div>
    """)


@router.post("/verify-code", response_model=None)
async def verify_code_endpoint(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    username = normalize_username(str(form.get("username", "")))
    code = str(form.get("code", ""))

    user_id = verify_code(username, code)
    if user_id is None:
        return _page("""
        <div class="card"><h1>Неверный или истёкший код</h1>
        <p>Запросите новый код заново.</p>
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
