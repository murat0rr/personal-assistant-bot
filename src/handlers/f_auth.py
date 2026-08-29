import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.core.config import settings
from src.core.db import async_session
from src.handlers.mode_buttons import MAIN_KEYBOARD
from src.models.authorized_user import AuthorizedUser

logger = logging.getLogger(__name__)

router = Router()


class AuthStates(StatesGroup):
    awaiting_password = State()


@router.message(StateFilter(AuthStates.awaiting_password), F.text)
async def handle_password_attempt(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    entered = (message.text or "").strip().lower()
    expected = settings.bot_access_password.strip().lower()
    if entered != expected:
        await message.answer("Неверный пароль, попробуй ещё раз.")
        return

    async with async_session() as session:
        existing = await session.get(AuthorizedUser, message.from_user.id)
        if existing is None:
            session.add(
                AuthorizedUser(
                    telegram_user_id=message.from_user.id,
                    added_at=datetime.now(ZoneInfo(settings.timezone)),
                )
            )
            await session.commit()

    await state.clear()
    logger.info("Новый авторизованный пользователь: %s", message.from_user.id)
    await message.answer("Готово, теперь можешь пользоваться ботом.", reply_markup=MAIN_KEYBOARD)
