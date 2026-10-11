import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.feedback import create_feedback
from src.core.message_text import extract_text

logger = logging.getLogger(__name__)

router = Router()


class FeedbackStates(StatesGroup):
    awaiting_text = State()


async def submit_feedback(message: Message, text: str) -> None:
    """Единственное место, где отзыв реально сохраняется (Phase 85,
    предложение: https://claude.ai/artifact/8xwZx1gqfuuM2KRKmSrNfA) —
    вызывается и из кнопки-режима "💬 Отзыв" (mode_buttons.py), и из
    классификации intent'а (orchestrator.py), и из команды /feedback
    ниже. Делает ровно одно: INSERT + честный ответ. Никакого похода в
    код/файлы — дальше текст видит только ИИ-триаж (классификатор, не
    исполнитель, см. core/feedback.py) и периодический агент по своему
    отдельному, секретом защищённому каналу."""
    if not message.from_user:
        return
    try:
        await create_feedback(message.from_user.id, text)
    except Exception:
        logger.exception("Не удалось сохранить отзыв: %r", text)
        await message.answer("Не получилось записать отзыв, попробуй ещё раз.")
        return

    await message.answer(
        "Спасибо, записал! Если это явный баг без влияния на дизайн — "
        "возможно, починится само в ближайшей проверке. Идею или что-то "
        "неоднозначное посмотрю и решу сам."
    )


@router.message(Command("feedback"))
async def handle_feedback_command(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    assert message.text is not None
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await submit_feedback(message, parts[1].strip())
        return

    await state.set_state(FeedbackStates.awaiting_text)
    await message.answer("Опиши баг, идею или пожелание — одним сообщением (можно голосом).")


@router.message(StateFilter(FeedbackStates.awaiting_text), F.voice | F.text)
async def handle_feedback_text(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    await state.clear()
    text = await extract_text(message)
    if not text:
        return
    await submit_feedback(message, text)
