import logging
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ButtonStyle
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichMessage,
    Message,
    RichMessageButton,
)

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.day_reviews import entries_since, save_diary_entry
from src.core.user_location import user_today
from src.integrations.claude_client import summarize_diary

# Окно "недавнего прошлого" для summarize_diary (ТЕХДОЛГ, 2026-10-20) —
# неделя назад от сегодня, тот же порядок величины, что у недельного
# ревью (f11_weekly_review.py). Только уже готовые саммари (не сырые
# ответы) — дешевле по токенам, и этого достаточно, чтобы заметить
# повторяющийся паттерн за несколько дней.
_DIARY_HISTORY_DAYS = 7


async def _recent_diary_summaries_text(user_id: int, today: date) -> str | None:
    entries = await entries_since(user_id, today - timedelta(days=_DIARY_HISTORY_DAYS))
    lines = [
        f"{e['entry_date'].strftime('%d.%m')}: {e['summary']}"
        for e in sorted(entries, key=lambda e: e["entry_date"])
        if e["summary"]
    ]
    return "\n".join(lines) or None


logger = logging.getLogger(__name__)

router = Router()

_RATING_FIELDS = ("physical", "social", "productivity", "happiness")
_RATING_LABELS = {
    "physical": "Физическая активность",
    "social": "Социальная активность",
    "productivity": "Продуктивность",
    "happiness": "Общее счастье",
}


class DiaryStates(StatesGroup):
    # Четыре оценки — ОДНО Rich Message сообщение (фидбек, 2026-10-22:
    # "возьми логику кнопок из /set_day_task" — тот же приём, тап по
    # кнопке правит сообщение на месте, а не шлёт новое на каждый
    # вопрос), см. _build_ratings_rich_message/handle_rating_button
    # ниже. highlight/reflection остаются отдельными текстовыми
    # вопросами — Rich Message кнопки физически не могут принять
    # свободный текст, только callback, этим двум ответ нужен реальным
    # сообщением от пользователя.
    ratings = State()
    highlight = State()
    reflection = State()


# (состояние, текст вопроса, тип, следующее состояние или None — конец опроса)
# — только текстовые вопросы, оценки через _QUESTIONS больше не идут,
# см. DiaryStates.ratings выше.
_QUESTIONS: list[tuple[State, str, str, State | None]] = [
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
    DiaryStates.highlight: "highlight",
    DiaryStates.reflection: "reflection",
}
_STATE_BY_FIELD = {name: state for state, name in _FIELD_NAMES.items()}


def _skip_keyboard(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data=f"diary:skip:{field}")]
        ]
    )


def _build_ratings_rich_message(ratings: dict[str, int | None]) -> InputRichMessage:
    """Четыре оценки одним сообщением (см. DiaryStates.ratings) — по
    строке на оценку: подпись + ряд кнопок 1/2/3, выбранное значение
    подсвечено (тот же приём SUCCESS/PRIMARY, что у done-кнопки в
    f_set_day_task.py). Можно менять любую оценку в любом порядке,
    сколько угодно раз, пока не выставлены все четыре."""
    blocks: list = [InputRichBlockSectionHeading(text="Как прошёл день? (1-3)", size=2)]
    for field in _RATING_FIELDS:
        value = ratings.get(field)
        blocks.append(InputRichBlockParagraph(text=_RATING_LABELS[field]))
        buttons = [
            RichMessageButton(
                text=str(v),
                style=ButtonStyle.SUCCESS if value == v else ButtonStyle.PRIMARY,
                callback_data=f"diaryrating:{field}:{v}",
            )
            for v in (1, 2, 3)
        ]
        blocks.append(InputRichBlockButtons(buttons=buttons))
    return InputRichMessage(blocks=blocks)


async def ask_ratings(bot: Bot, state: FSMContext) -> None:
    """Точка входа вечернего опроса (сменила ask_question(..., physical)
    — см. scheduler/jobs.py::_evening_diary) — шлёт ОДНО сообщение с
    четырьмя оценками сразу, без отдельного вопроса на каждую."""
    rich_message = _build_ratings_rich_message({})
    sent = await bot.send_rich_message(chat_id=settings.telegram_user_id, rich_message=rich_message)
    await state.update_data(_ratings_chat_id=sent.chat.id, _ratings_message_id=sent.message_id)
    await state.set_state(DiaryStates.ratings)


async def ask_question(bot: Bot, state: FSMContext, target: State) -> None:
    _, text, _, _ = _QUESTIONS_BY_STATE[target]
    field = _FIELD_NAMES[target]
    await bot.send_message(
        chat_id=settings.telegram_user_id, text=text, reply_markup=_skip_keyboard(field)
    )
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
            past_entries_text = await _recent_diary_summaries_text(settings.telegram_user_id, today)
            summary = await summarize_diary(text_for_summary, past_entries_text)
        # Один апсерт разом на все поля (Phase 62 — раньше запись
        # уходила в Notion, а Postgres дублировал только саммари
        # отдельным вызовом; теперь Postgres — единственный источник
        # правды, дублировать нечего).
        await save_diary_entry(
            settings.telegram_user_id, today, ratings, highlight, reflection, summary
        )
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
    await bot.send_message(chat_id=settings.telegram_user_id, text=reply)
    await state.clear()


@router.callback_query(F.data.startswith("diaryrating:"))
async def handle_rating_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Тап по одной из 1/2/3 кнопок в консолидированном сообщении
    (_build_ratings_rich_message) — правит СВОЁ же сообщение на месте
    (тот же приём, что toggle в f_set_day_task.py), можно переставлять
    оценку сколько угодно раз. Как только выставлены все четыре —
    переходит к текстовым вопросам (highlight)."""
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if (
        not callback.data
        or not isinstance(callback.message, Message)
        or callback.message.bot is None
    ):
        return

    if await state.get_state() != DiaryStates.ratings.state:
        await callback.answer("Этот вопрос уже неактуален", show_alert=True)
        return

    _, field, value_str = callback.data.split(":")
    value = int(value_str)
    await state.update_data(**{field: value})
    await callback.answer(f"Отмечено: {value}")

    data = await state.get_data()
    ratings = {f: data.get(f) for f in _RATING_FIELDS}
    rich_message = _build_ratings_rich_message(ratings)
    await callback.message.bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        rich_message=rich_message,
    )

    if all(ratings[f] is not None for f in _RATING_FIELDS):
        await ask_question(callback.message.bot, state, DiaryStates.highlight)


@router.callback_query(F.data.startswith("diary:"))
async def handle_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Теперь только "Пропустить" у текстовых вопросов (highlight/
    reflection) — оценки больше не идут этим путём, см.
    handle_rating_button выше."""
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
    field = parts[2]
    current = await state.get_state()
    current_state_obj = _STATE_BY_FIELD.get(field)

    if current_state_obj is None or current != current_state_obj.state:
        await callback.answer("Этот вопрос уже неактуален", show_alert=True)
        return

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
