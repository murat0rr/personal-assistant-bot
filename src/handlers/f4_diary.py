import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.integrations.claude_client import summarize_diary
from src.integrations.notion import create_diary_entry

logger = logging.getLogger(__name__)

router = Router()


class DiaryStates(StatesGroup):
    physical = State()
    social = State()
    productivity = State()
    happiness = State()
    highlight = State()
    reflection = State()


# (состояние, текст вопроса, тип, следующее состояние или None — конец опроса)
_QUESTIONS: list[tuple[State, str, str, State | None]] = [
    (DiaryStates.physical, "Физическая активность сегодня (1-3)?", "rating", DiaryStates.social),
    (
        DiaryStates.social,
        "Социальная активность сегодня (1-3)?",
        "rating",
        DiaryStates.productivity,
    ),
    (DiaryStates.productivity, "Продуктивность сегодня (1-3)?", "rating", DiaryStates.happiness),
    (DiaryStates.happiness, "Общее счастье сегодня (1-3)?", "rating", DiaryStates.highlight),
    (
        DiaryStates.highlight,
        "Была ли сегодня какая-то особенность? (можно пропустить — просто отправь «-»)",
        "text",
        DiaryStates.reflection,
    ),
    (
        DiaryStates.reflection,
        "Есть что осмыслить/отрефлексировать за день? (можно «-»)",
        "text",
        None,
    ),
]
_QUESTIONS_BY_STATE = {q[0]: q for q in _QUESTIONS}
_FIELD_NAMES = {
    DiaryStates.physical: "physical",
    DiaryStates.social: "social",
    DiaryStates.productivity: "productivity",
    DiaryStates.happiness: "happiness",
    DiaryStates.highlight: "highlight",
    DiaryStates.reflection: "reflection",
}
_LABELS = {
    "physical": "Физическая активность",
    "social": "Социальная активность",
    "productivity": "Продуктивность",
    "happiness": "Общее счастье",
    "highlight": "Особенность дня",
    "reflection": "Рефлексия",
}


def _rating_keyboard(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(v), callback_data=f"diary:{field}:{v}")
                for v in (1, 2, 3)
            ]
        ]
    )


async def ask_question(bot: Bot, state: FSMContext, target: State) -> None:
    _, text, kind, _ = _QUESTIONS_BY_STATE[target]
    field = _FIELD_NAMES[target]
    reply_markup = _rating_keyboard(field) if kind == "rating" else None
    await bot.send_message(chat_id=settings.telegram_user_id, text=text, reply_markup=reply_markup)
    await state.set_state(target)


async def _advance(bot: Bot, state: FSMContext, current: State) -> None:
    _, _, _, next_state = _QUESTIONS_BY_STATE[current]
    if next_state is None:
        await _finish(bot, state)
        return
    await ask_question(bot, state, next_state)


async def _finish(bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    today = datetime.now(ZoneInfo(settings.timezone)).date()

    answers_text = "\n".join(
        f"{_LABELS[field]}: {data.get(field, '-')}" for field in _FIELD_NAMES.values()
    )

    try:
        summary = await summarize_diary(answers_text)
        url = await create_diary_entry(today, answers_text, summary)
    except Exception:
        logger.exception("Не удалось сохранить дневник за %s", today)
        await bot.send_message(
            chat_id=settings.telegram_user_id,
            text="Не получилось сохранить дневник, ответы потеряны — извини.",
        )
        await state.clear()
        return

    await bot.send_message(
        chat_id=settings.telegram_user_id,
        text=f"Записал дневник за {today.strftime('%d.%m.%Y')}.\n{summary}\n{url}",
    )
    await state.clear()


@router.callback_query(F.data.startswith("diary:"))
async def handle_rating(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if (
        not callback.data
        or not isinstance(callback.message, Message)
        or callback.message.bot is None
    ):
        return

    _, field, value = callback.data.split(":")
    current = await state.get_state()

    current_state_obj = next((s for s, name in _FIELD_NAMES.items() if name == field), None)
    if current_state_obj is None or current != current_state_obj.state:
        await callback.answer("Этот вопрос уже неактуален", show_alert=True)
        return

    await state.update_data(**{field: int(value)})
    await callback.answer(f"Отмечено: {value}")
    await callback.message.edit_reply_markup(reply_markup=None)
    await _advance(callback.message.bot, state, current_state_obj)


@router.message(StateFilter(DiaryStates.highlight, DiaryStates.reflection))
async def handle_text_answer(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_authorized(message.from_user.id) or message.bot is None:
        return

    current = await state.get_state()
    current_state_obj = next(
        (s for s in (DiaryStates.highlight, DiaryStates.reflection) if s.state == current), None
    )
    if current_state_obj is None:
        return

    field = _FIELD_NAMES[current_state_obj]
    answer = message.text or ""
    await state.update_data(**{field: "-" if answer.strip() == "-" else answer})
    await _advance(message.bot, state, current_state_obj)
