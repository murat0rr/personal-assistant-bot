"""Подключение Google Calendar (Phase 64) — /google_calendar присылает
ссылку на согласие, /google_calendar_off отключает. Сама синхронизация
— core/google_calendar_sync.py, вызывается по расписанию (см.
scheduler/jobs.py).

Client ID/Secret — один на всё приложение, в .env (тот же принцип, что
у остальных ключей — Claude, Notion), не по одному на пользователя.
Пока не заданы, /google_calendar сама объясняет, что и куда добавить —
раньше отвечала бесполезным "обратитесь к владельцу бота", хотя
владелец обычно и есть тот, кто спрашивает (см. историю в SPEC.md)."""

from urllib.parse import urlsplit

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.db import async_session
from src.core.google_oauth_state import generate_state
from src.integrations.google_calendar import build_auth_url
from src.models.google_calendar_account import GoogleCalendarAccount

router = Router()


def _guessed_redirect_uri() -> str:
    """Домен берём из уже настроенного MINIAPP_URL (та же схема+хост,
    что и у боевого Mini App) — не дублируем его отдельной переменной
    ради одной строки гайда. Если MINIAPP_URL тоже пуст (совсем свежая
    установка), отдаём заполнитель — редко случается по отдельности от
    самого MINIAPP_URL."""
    if settings.miniapp_url:
        parts = urlsplit(settings.miniapp_url)
        return f"{parts.scheme}://{parts.netloc}/google/oauth/callback"
    return "https://<ваш-домен>/google/oauth/callback"


_SETUP_GUIDE = (
    "Google Calendar пока не настроен. Что сделать один раз:\n\n"
    "1. console.cloud.google.com → создать проект (или выбрать существующий).\n"
    "2. «APIs & Services» → «Library» → включить Google Calendar API.\n"
    "3. «APIs & Services» → «Credentials» → «Create Credentials» → "
    "«OAuth client ID», тип — Web application.\n"
    "4. В «Authorized redirect URIs» добавить ровно:\n{redirect_uri}\n"
    "5. Скопировать Client ID и Client Secret.\n"
    "6. «OAuth consent screen» → «Test users» → добавить свой же Google-аккаунт "
    "(приложение не проходит верификацию Google, без этого шага он покажет "
    "предупреждение и не пустит дальше).\n"
    "7. Вписать в .env на сервере и передеплоить:\n"
    "GOOGLE_CLIENT_ID=...\nGOOGLE_CLIENT_SECRET=...\n"
    "GOOGLE_OAUTH_REDIRECT_URI={redirect_uri}\n\n"
    "После этого пришлите /google_calendar ещё раз — пришлю ссылку на согласие."
)


@router.message(Command("google_calendar"))
async def handle_google_calendar_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        return
    if not settings.google_client_id:
        await message.answer(_SETUP_GUIDE.format(redirect_uri=_guessed_redirect_uri()))
        return

    user_id = message.from_user.id
    state = await generate_state(user_id)
    url = build_auth_url(state)
    await message.answer(
        f"Разрешите доступ к основному календарю по ссылке (действует 10 минут):\n{url}\n\n"
        "События появятся в задачах в течение ближайших минут после подтверждения. "
        "Отключить — /google_calendar_off."
    )


@router.message(Command("google_calendar_off"))
async def handle_google_calendar_off_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        return

    user_id = message.from_user.id
    async with async_session() as session:
        existing = await session.get(GoogleCalendarAccount, user_id)
        if existing is None:
            await message.answer("Google Calendar и так не подключён.")
            return
        await session.delete(existing)
        await session.commit()
    await message.answer(
        "Google Calendar отключён. Уже созданные из календаря задачи остаются "
        "как обычные — они больше не будут обновляться и удаляться сами."
    )
