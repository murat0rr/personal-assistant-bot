"""Команда `/widget_token` (2026-10-25) — выдаёт долгоживущий токен
для виджета на главном экране телефона (Scriptable на iOS, Tasker на
Android): вставляется один раз в конфиг виджета, дальше сам виджет
ходит за данными напрямую на `src/adapters/widget_api.py`, минуя бота.

Read-only со стороны виджета — эта команда только ВЫДАЁТ токен, сам
просмотр задач происходит на отдельном эндпоинте."""

from urllib.parse import urlparse

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.widget_token import create_widget_token

router = Router()


@router.message(Command("widget_token"))
async def handle_widget_token_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    if not settings.miniapp_url:
        await message.answer("Виджет не настроен — пусто MINIAPP_URL в .env.")
        return

    token = create_widget_token(message.from_user.id)
    base = urlparse(settings.miniapp_url)
    url = f"{base.scheme}://{base.netloc}/widget/today-tasks"
    await message.answer(
        f"Токен для виджета (действует ~год, никому не показывай):\n"
        f"`{token}`\n\n"
        f"В Scriptable/Tasker — запрос GET {url} с заголовком "
        f"Authorization: Bearer <токен>, ответ — JSON со списком задач "
        f"на сегодня. Чтобы заменить токен — вызови команду снова.",
        parse_mode="Markdown",
    )
