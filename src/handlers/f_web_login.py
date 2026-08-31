"""Команда /webcode (Phase 45, вторая переделка входа в веб-версию) —
пользователь сам пишет боту, а не сайт ищет его по username через Bot
API (getChat по @username оказался ненадёжен для приватных чатов —
живая проверка, "chat not found" даже для уже переписывавшегося
пользователя). Так user_id известен сразу из входящего сообщения, без
всякого резолвинга: message.from_user.id — тот же источник личности,
что и у всех остальных команд бота."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.login_codes import can_request_code, generate_code

router = Router()


@router.message(Command("webcode"))
async def handle_webcode_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    user_id = message.from_user.id
    if not can_request_code(user_id):
        await message.answer("Код уже отправлен — подождите минуту перед повторным запросом.")
        return

    code = generate_code(user_id)
    await message.answer(
        f"Код для входа в веб-версию: {code}\nДействует 5 минут, никому не сообщайте."
    )
