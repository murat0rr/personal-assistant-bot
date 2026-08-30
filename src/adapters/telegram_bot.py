import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.message_tracking import attach_message_tracking, track_incoming
from src.core.orchestrator import router as orchestrator_router
from src.handlers.f4_diary import router as diary_router
from src.handlers.f9_finance import router as finance_router
from src.handlers.f_auth import AuthStates
from src.handlers.f_auth import router as auth_router
from src.handlers.f_reminders import router as reminders_router
from src.handlers.mode_buttons import MAIN_KEYBOARD
from src.handlers.mode_buttons import router as mode_buttons_router
from src.scheduler.jobs import setup_scheduler

logger = logging.getLogger(__name__)

# RedisStorage переживает рестарт контейнера (важно — вечерний опрос может
# идти как раз в момент деплоя); без REDIS_URL откатываемся на память.
storage = RedisStorage.from_url(settings.redis_url) if settings.redis_url else MemoryStorage()
dp = Dispatcher(storage=storage)
dp.message.outer_middleware(track_incoming)

# auth_router, diary_router и mode_buttons_router — раньше orchestrator_router:
# пока активен FSM (ввод пароля, опрос дневника, ожидание содержимого после
# кнопки-режима), сообщения должны ловиться по state, а не падать в общий capture.
dp.include_router(auth_router)
dp.include_router(diary_router)
dp.include_router(mode_buttons_router)
dp.include_router(reminders_router)
dp.include_router(finance_router)
dp.include_router(orchestrator_router)


@dp.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    if await is_authorized(message.from_user.id):
        await message.answer("Привет! Я на связи.", reply_markup=MAIN_KEYBOARD)
        return
    await state.set_state(AuthStates.awaiting_password)
    await message.answer("Привет! Чтобы пользоваться ботом, введи пароль:")


@dp.message(Command("staging"))
async def handle_staging(message: Message) -> None:
    # Лёгкий staging для Mini App (SPEC.md §5) — открывает /miniapp-staging/
    # через настоящий Telegram WebView с подписанным initData: обычный
    # браузер на этот URL получил бы 401 от /miniapp/api/* (initData пуст),
    # а часть багов (например ненадёжный setPointerCapture в Telegram
    # WebView) вообще не воспроизводится вне реального клиента — см.
    # staging_static/README.md за workflow (scp кандидата перед мержем).
    if not message.from_user or not await is_authorized(message.from_user.id):
        return
    if not settings.staging_miniapp_url:
        await message.answer("Staging не настроен — пусто STAGING_MINIAPP_URL в .env.")
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть staging Mini App",
                    web_app=WebAppInfo(url=settings.staging_miniapp_url),
                )
            ]
        ]
    )
    await message.answer(
        "Откроет то, что сейчас лежит в staging_static/ на сервере — "
        "не обязательно смёрженное в master.",
        reply_markup=keyboard,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.telegram_bot_token)
    attach_message_tracking(bot)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать / показать кнопки"),
            BotCommand(command="reminders", description="Список напоминаний"),
            BotCommand(command="staging", description="Открыть staging Mini App"),
        ]
    )

    # Задачи и привычки теперь в Postgres (Phase 10) — никакого синка с
    # Notion перед стартом планировщика больше не нужно, джобы стартуют
    # безусловно.
    scheduler = setup_scheduler(bot, dp.storage)
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
