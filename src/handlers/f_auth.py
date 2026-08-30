import logging
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.config import settings
from src.core.db import async_session
from src.core.onboarding import seed_onboarding_data
from src.core.user_location import user_today
from src.handlers.mode_buttons import MAIN_KEYBOARD
from src.models.authorized_user import AuthorizedUser
from src.scheduler.jobs import register_jobs_for_user

logger = logging.getLogger(__name__)

router = Router()

_WELCOME_TEXT = (
    "Готово, теперь можешь пользоваться ботом.\n\n"
    "Набросал пару пробных задач, проект и цель — чтобы было на чём "
    "посмотреть, как всё устроено, можно смело удалить или переделать "
    "под себя.\n\n"
    "Если что-то будет непонятно — загляни в «Помощь» (☰ в углу "
    "расширенного экрана Mini App), там разобраны все жесты и разделы."
)


class AuthStates(StatesGroup):
    awaiting_password = State()


@router.message(StateFilter(AuthStates.awaiting_password), F.text)
async def handle_password_attempt(
    message: Message, state: FSMContext, scheduler: AsyncIOScheduler, storage: BaseStorage
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id

    entered = (message.text or "").strip().lower()
    expected = settings.bot_access_password.strip().lower()
    # secrets.compare_digest — сравнение за постоянное время (Phase 39,
    # ревизия безопасности): обычное `!=` возвращает результат тем
    # быстрее, чем раньше совпадение оборвалось, — теоретическая утечка
    # пароля по времени ответа. Тот же приём уже используется для
    # секрета вебхуков Tasker (см. _verify_secret).
    if not secrets.compare_digest(entered, expected):
        await message.answer("Неверный пароль, попробуй ещё раз.")
        return

    async with async_session() as session:
        existing = await session.get(AuthorizedUser, user_id)
        is_new = existing is None
        if is_new:
            session.add(
                AuthorizedUser(
                    telegram_user_id=user_id,
                    added_at=datetime.now(ZoneInfo(settings.timezone)),
                )
            )
            await session.commit()

    await state.clear()

    if not is_new:
        # Пароль уже вводился раньше этим же пользователем (например,
        # состояние FSM зависло) — не пересоздаём аккаунт/джобы/затравку
        # заново, просто пускаем.
        logger.info("Повторный ввод пароля уже авторизованным: %s", user_id)
        await message.answer(
            "Готово, теперь можешь пользоваться ботом.", reply_markup=MAIN_KEYBOARD
        )
        return

    logger.info("Новый авторизованный пользователь: %s", user_id)

    # Многопользовательская авторизация (Phase 40) — с этого момента у
    # пользователя есть свой набор данных: личные джобы планировщика
    # (сводки/напоминания/итоги недели и т.д., в его часовом поясе — по
    # умолчанию таком же, как у владельца, пока не вызовет /timezone) и
    # затравочные пробные задача/проект/цель/шаблон, чтобы было на чём
    # сразу попробовать интерфейс, а не начинать с пустого экрана.
    try:
        await register_jobs_for_user(scheduler, message.bot, storage, user_id)
    except Exception:
        logger.exception("Не удалось зарегистрировать джобы для нового пользователя %s", user_id)

    try:
        today = await user_today(user_id)
        await seed_onboarding_data(user_id, today)
    except Exception:
        logger.exception("Не удалось создать затравочные данные для %s", user_id)

    await message.answer(_WELCOME_TEXT, reply_markup=MAIN_KEYBOARD)
