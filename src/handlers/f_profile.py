import logging

from aiogram import Bot, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.user_profile import save_profile_from_answers

logger = logging.getLogger(__name__)

router = Router()


class ProfileStates(StatesGroup):
    wishes = State()
    goals = State()
    thinking = State()
    routine = State()
    extra = State()


# (состояние, текст вопроса, следующее состояние или None — конец опроса)
# — тот же декларативный приём, что DiaryStates/_QUESTIONS в f4_diary.py,
# но линейно и без рейтинг-кнопок: здесь все вопросы свободным текстом,
# опрос не про сегодняшний день, а разовый ввод о себе (Phase 98).
_QUESTIONS: list[tuple[State, str, State | None]] = [
    (
        ProfileStates.wishes,
        "Что бы ты хотел получать от этого бота? Какие у тебя ожидания?",
        ProfileStates.goals,
    ),
    (
        ProfileStates.goals,
        "Какие у тебя сейчас главные цели — в работе, учёбе, личном?",
        ProfileStates.thinking,
    ),
    (
        ProfileStates.thinking,
        "Как ты обычно мыслишь и принимаешь решения — есть особенности, которые стоит знать?",
        ProfileStates.routine,
    ),
    (
        ProfileStates.routine,
        "Какой у тебя обычно распорядок дня — во сколько встаёшь, работаешь, отдыхаешь?",
        ProfileStates.extra,
    ),
    (ProfileStates.extra, "Что ещё важное о себе стоит знать боту?", None),
]
_QUESTIONS_BY_STATE = {q[0]: q for q in _QUESTIONS}
_FIELD_NAMES = {
    ProfileStates.wishes: "wishes",
    ProfileStates.goals: "goals",
    ProfileStates.thinking: "thinking",
    ProfileStates.routine: "routine",
    ProfileStates.extra: "extra",
}


async def ask_question(bot: Bot, state: FSMContext, user_id: int, target: State) -> None:
    _, text, _ = _QUESTIONS_BY_STATE[target]
    await bot.send_message(chat_id=user_id, text=text)
    await state.set_state(target)


async def _advance(bot: Bot, state: FSMContext, user_id: int, current: State) -> None:
    _, _, next_state = _QUESTIONS_BY_STATE[current]
    if next_state is None:
        await _finish(bot, state, user_id)
        return
    await ask_question(bot, state, user_id, next_state)


async def _finish(bot: Bot, state: FSMContext, user_id: int) -> None:
    data = await state.get_data()
    # Ключ — сам текст вопроса (не техническое имя поля) — так
    # aggregate_user_profile (claude_client.py) получает человекочитаемую
    # пару "вопрос/ответ", не обязан знать про внутренние имена состояний.
    answers = {
        question: (data.get(_FIELD_NAMES[state_obj]) or "").strip()
        for state_obj, question, _ in _QUESTIONS
    }
    answers = {q: a for q, a in answers.items() if a}

    if not answers:
        await bot.send_message(
            chat_id=user_id,
            text="Пустой опрос — профиль не сохранён, можешь пройти заново: /profile",
        )
        await state.clear()
        return

    try:
        summary = await save_profile_from_answers(user_id, answers)
    except Exception:
        logger.exception("Не удалось собрать профиль для %s", user_id)
        await bot.send_message(
            chat_id=user_id, text="Не получилось собрать профиль, попробуй ещё раз: /profile"
        )
        await state.clear()
        return

    await bot.send_message(
        chat_id=user_id,
        text=f"Профиль сохранён. Вот что я понял:\n\n{summary}",
    )
    await state.clear()


@router.message(Command("profile"))
async def handle_profile_command(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        return
    if message.bot is None:
        return
    # Повторный вызов начинает опрос заново — старый профиль
    # перезаписывается только по завершении (_finish), не раньше, так
    # что обрыв на середине повторного прохода не теряет прежний.
    await ask_question(message.bot, state, message.from_user.id, ProfileStates.wishes)


@router.message(StateFilter(*(q[0] for q in _QUESTIONS)))
async def handle_text_answer(message: Message, state: FSMContext) -> None:
    if (
        not message.from_user
        or not await is_authorized(message.from_user.id)
        or message.bot is None
    ):
        return

    current = await state.get_state()
    current_state_obj = next((s for s, _, _ in _QUESTIONS if s.state == current), None)
    if current_state_obj is None:
        return

    field = _FIELD_NAMES[current_state_obj]
    await state.update_data(**{field: message.text or ""})
    await _advance(message.bot, state, message.from_user.id, current_state_obj)
