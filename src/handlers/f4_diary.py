import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.day_reviews import save_review
from src.core.user_location import user_today
from src.integrations.claude_client import summarize_diary
from src.integrations.notion import create_diary_entry

logger = logging.getLogger(__name__)

router = Router()

_RATING_FIELDS = ("physical", "social", "productivity", "happiness")


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
        "Была ли сегодня какая-то особенность?",
        "text",
        DiaryStates.reflection,
    ),
    (
        DiaryStates.reflection,
        "Есть что осмыслить/отрефлексировать за день?",
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
_STATE_BY_FIELD = {name: state for state, name in _FIELD_NAMES.items()}


def _rating_keyboard(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(v), callback_data=f"diary:rate:{field}:{v}")
                for v in (1, 2, 3)
            ]
        ]
    )


def _skip_keyboard(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data=f"diary:skip:{field}")]
        ]
    )


async def ask_question(bot: Bot, state: FSMContext, target: State) -> None:
    _, text, kind, _ = _QUESTIONS_BY_STATE[target]
    field = _FIELD_NAMES[target]
    reply_markup = _rating_keyboard(field) if kind == "rating" else _skip_keyboard(field)
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
    # Дневник — только у владельца (Phase 40), поэтому личный часовой
    # пояс — его собственный (Phase 43: тот же класс бага, что и в
    # api.py — settings.timezone мог не совпадать с реальным поясом).
    today = await user_today(settings.telegram_user_id)

    ratings = {field: data.get(field) for field in _RATING_FIELDS}
    highlight = data.get("highlight") or None
    reflection = data.get("reflection") or None

    try:
        summary = None
        if highlight or reflection:
            text_for_summary = "\n".join(part for part in (highlight, reflection) if part)
            summary = await summarize_diary(text_for_summary)
        url = await create_diary_entry(today, ratings, highlight, reflection, summary)
        # Дублируем уже посчитанный саммари в Postgres (Phase 48) — тут
        # же, а не отдельным заходом, чтобы Notion и Postgres версия
        # ревью дня не могли разойтись между собой: либо весь дневник за
        # день сохранился, либо (см. except ниже) ничего.
        if summary:
            await save_review(settings.telegram_user_id, today, summary)
    except Exception:
        logger.exception("Не удалось сохранить дневник за %s", today)
        await bot.send_message(
            chat_id=settings.telegram_user_id,
            text="Не получилось сохранить дневник, ответы потеряны — извини.",
        )
        await state.clear()
        return

    reply = f"Записал дневник за {today.strftime('%d.%m.%Y')}."
    if summary:
        reply += f"\n{summary}"
    reply += f"\n{url}"
    await bot.send_message(chat_id=settings.telegram_user_id, text=reply)
    await state.clear()


@router.callback_query(F.data.startswith("diary:"))
async def handle_button(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if (
        not callback.data
        or not isinstance(callback.message, Message)
        or callback.message.bot is None
    ):
        return

    parts = callback.data.split(":")
    action, field = parts[1], parts[2]
    current = await state.get_state()
    current_state_obj = _STATE_BY_FIELD.get(field)

    if current_state_obj is None or current != current_state_obj.state:
        await callback.answer("Этот вопрос уже неактуален", show_alert=True)
        return

    if action == "rate":
        value = int(parts[3])
        await state.update_data(**{field: value})
        await callback.answer(f"Отмечено: {value}")
    else:
        await state.update_data(**{field: ""})
        await callback.answer("Пропущено")

    await callback.message.edit_reply_markup(reply_markup=None)
    await _advance(callback.message.bot, state, current_state_obj)


@router.message(StateFilter(DiaryStates.highlight, DiaryStates.reflection))
async def handle_text_answer(message: Message, state: FSMContext) -> None:
    if (
        not message.from_user
        or not await is_authorized(message.from_user.id)
        or message.bot is None
    ):
        return

    current = await state.get_state()
    current_state_obj = next(
        (s for s in (DiaryStates.highlight, DiaryStates.reflection) if s.state == current), None
    )
    if current_state_obj is None:
        return

    field = _FIELD_NAMES[current_state_obj]
    await state.update_data(**{field: message.text or ""})
    await _advance(message.bot, state, current_state_obj)
