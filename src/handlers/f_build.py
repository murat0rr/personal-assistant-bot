import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.core.build import (
    append_clarification,
    create_build_request,
    get_active_build,
    get_build,
    set_build_status,
)
from src.core.config import settings
from src.core.message_text import extract_text

logger = logging.getLogger(__name__)

router = Router()

_STATUS_LABELS = {
    "pending_plan": "разбираюсь, план ещё не готов",
    "awaiting_approval": "план готов, жду твоего решения",
    "approved": "одобрено, жду реализации",
    "in_progress": "реализую прямо сейчас",
}


class BuildStates(StatesGroup):
    awaiting_text = State()
    awaiting_clarification = State()


def _is_owner(user_id: int) -> bool:
    return user_id == settings.telegram_user_id


async def _start_build(message: Message, text: str) -> None:
    if not message.from_user:
        return
    active = await get_active_build(message.from_user.id)
    if active is not None:
        label = _STATUS_LABELS.get(active["status"], active["status"])
        await message.answer(
            f"Уже работаю над запросом #{active['id']} ({label}) — "
            "дождись завершения или сначала отклони его кнопкой в плане."
        )
        return

    try:
        await create_build_request(message.from_user.id, message.chat.id, text)
    except Exception:
        logger.exception("Не удалось создать build-запрос: %r", text)
        await message.answer("Не получилось принять запрос, попробуй ещё раз.")
        return

    await message.answer("Принял, разбираюсь в коде — пришлю план в течение нескольких минут.")


@router.message(Command("build"))
async def handle_build_command(message: Message, state: FSMContext) -> None:
    # Строго владелец (не is_authorized) — твой текст здесь не данные
    # для классификации, а легитимная инструкция агенту, видеть и
    # запускать это может только твой аккаунт (см. предложение:
    # https://claude.ai/artifact/8xwZx1gqfuuM2KRKmSrNfA, §8).
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    assert message.text is not None
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await _start_build(message, parts[1].strip())
        return

    await state.set_state(BuildStates.awaiting_text)
    await message.answer("Что реализовать? Опиши — можно масштабно, одним сообщением.")


@router.message(StateFilter(BuildStates.awaiting_text), F.voice | F.text)
async def handle_build_text(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    await state.clear()
    text = await extract_text(message)
    if not text:
        return
    await _start_build(message, text)


async def _guarded_build(callback: CallbackQuery) -> int | None:
    """Общая проверка для всех трёх кнопок плана (Phase 85, живая
    проверка нашла реальный баг: тап по кнопке на СТАРОМ сообщении с
    планом мог откатить уже завершённый запрос обратно в "approved").
    Действуют только кнопки на планe, который всё ещё реально ждёт
    решения — тот же принцип "это уже неактуально", что у
    handle_sphere_pick/handle_goal_done в f_goals.py."""
    if not callback.data:
        return None
    build_id = int(callback.data.split(":")[2])
    build = await get_build(build_id)
    if build is None or build["status"] != "awaiting_approval":
        await callback.answer("Это уже неактуально", show_alert=True)
        return None
    return build_id


@router.callback_query(F.data.startswith("build:approve:"))
async def handle_build_approve(callback: CallbackQuery) -> None:
    if not callback.from_user or not _is_owner(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return

    build_id = await _guarded_build(callback)
    if build_id is None:
        return
    await set_build_status(build_id, "approved")
    await callback.answer("Одобрено")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"✅ Одобрено — #{build_id} уйдёт в реализацию в ближайшие минуты."
        )


@router.callback_query(F.data.startswith("build:reject:"))
async def handle_build_reject(callback: CallbackQuery) -> None:
    if not callback.from_user or not _is_owner(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return

    build_id = await _guarded_build(callback)
    if build_id is None:
        return
    await set_build_status(build_id, "rejected")
    await callback.answer("Отклонено")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"❌ Отклонено — #{build_id}, код не трогался.")


@router.callback_query(F.data.startswith("build:clarify:"))
async def handle_build_clarify(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_owner(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return

    build_id = await _guarded_build(callback)
    if build_id is None:
        return
    await state.set_state(BuildStates.awaiting_clarification)
    await state.update_data(build_id=build_id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Что поправить в понимании? Опиши уточнение.")


@router.message(StateFilter(BuildStates.awaiting_clarification), F.voice | F.text)
async def handle_build_clarification_text(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    data = await state.get_data()
    build_id = data.get("build_id")
    await state.clear()
    text = await extract_text(message)
    if not text or build_id is None:
        return

    try:
        await append_clarification(build_id, text)
    except Exception:
        logger.exception("Не удалось дописать уточнение к build-запросу %s", build_id)
        await message.answer("Не получилось сохранить уточнение, попробуй ещё раз.")
        return

    await message.answer("Принял уточнение — пересоберу план с ним в ближайшие минуты.")
