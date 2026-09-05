"""Подключение Google Calendar (Phase 64) — /google_calendar присылает
ссылку на согласие, /google_calendar_off отключает. Сама синхронизация
— core/google_calendar_sync.py, вызывается по расписанию (см.
scheduler/jobs.py)."""

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


@router.message(Command("google_calendar"))
async def handle_google_calendar_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        return
    if not settings.google_client_id:
        await message.answer("Google Calendar не настроен — обратитесь к владельцу бота.")
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
