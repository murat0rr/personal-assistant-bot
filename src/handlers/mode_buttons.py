from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from src.core.auth import is_authorized
from src.core.message_text import extract_text
from src.core.topics import TOPIC_STUBS, ensure_in_topic, get_or_create_topic
from src.handlers.f1_task_note import handle_task_note
from src.handlers.f_notes import handle_note
from src.handlers.f_question import handle_question_input
from src.handlers.f_recurring import (
    RecurringClarificationStates,
    handle_new_recurring_task,
    handle_recurring_clarification_answer,
)
from src.handlers.f_reminders import handle_new_reminder

router = Router()


class ModeStates(StatesGroup):
    task = State()
    note = State()
    question = State()
    reminder = State()
    recurring = State()


MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Задача"), KeyboardButton(text="🗒 Заметка")],
        [KeyboardButton(text="❓ Вопрос"), KeyboardButton(text="🔔 Напоминалка")],
        [KeyboardButton(text="🔁 Повторяющаяся")],
    ],
    resize_keyboard=True,
)

_BUTTON_PROMPTS: dict[str, tuple[State, str]] = {
    "📝 Задача": (ModeStates.task, "Окей, что за задача?"),
    "🗒 Заметка": (ModeStates.note, "Слушаю, что записать?"),
    "❓ Вопрос": (
        ModeStates.question,
        "Какой у тебя вопрос? Можно текстом, голосом, фото или PDF.",
    ),
    "🔔 Напоминалка": (ModeStates.reminder, "Когда и о чём напомнить?"),
    "🔁 Повторяющаяся": (
        ModeStates.recurring,
        "Опиши задачу и как часто её делать (например «каждый понедельник разгрести почту»).",
    ),
}

# Тема (Phase 81/82, Threaded Mode) на каждую кнопку — задача/напоминалка/
# повторяющаяся делят одну тему "Задачи", как и попросили.
_BUTTON_TOPIC_KEYS: dict[str, str] = {
    "📝 Задача": "tasks",
    "🗒 Заметка": "notes",
    "❓ Вопрос": "questions",
    "🔔 Напоминалка": "tasks",
    "🔁 Повторяющаяся": "tasks",
}

# ModeStates.question и ModeStates.recurring сюда не входят — у обоих
# свой хендлер ниже. У question — мультимодальный ввод (фото/PDF) и
# мгновенный ack, который generic-путь через extract_text не покрывает.
# У recurring (Phase 73) — диалог с уточняющим вопросом от Claude может
# продолжиться ещё на один (или несколько) ход, а generic-путь ниже
# безусловно чистит state ДО вызова хендлера — after that там уже
# негде было бы продолжить диалог.
_MODE_HANDLERS = {
    ModeStates.task: handle_task_note,
    ModeStates.note: handle_note,
    ModeStates.reminder: handle_new_reminder,
}

# Тема на каждое состояние — нужна content-хендлерам ниже для повторной
# проверки (см. handle_mode_content/handle_question_button): FSM-
# состояние в этом проекте общее на весь чат, не по темам, поэтому
# состояние могло стартовать из своей темы, а текст прийти уже из
# другой — только состояния из _BUTTON_TOPIC_KEYS, отображённые на те
# же ключи через _BUTTON_PROMPTS.
_STATE_TOPIC_KEYS: dict[str, str] = {
    state.state: _BUTTON_TOPIC_KEYS[button_text]
    for button_text, (state, _prompt) in _BUTTON_PROMPTS.items()
}


@router.message(F.text.in_(_BUTTON_PROMPTS.keys()))
async def handle_mode_button(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    assert message.text is not None

    # Своя тема на каждую кнопку (Phase 81/82, Threaded Mode). Кнопки
    # видны из любой темы чата (клавиатура не привязана к конкретной
    # теме), поэтому проверяем здесь же, до входа в состояние — иначе
    # ниже пришлось бы ловить и в content-хендлерах тоже (и таки
    # пришлось, см. handle_mode_content/handle_question_button: FSM-
    # состояние общее на весь чат, не по темам).
    topic_key = _BUTTON_TOPIC_KEYS[message.text]
    topic_id = await get_or_create_topic(message.bot, message.from_user.id, topic_key)
    if not await ensure_in_topic(message, topic_id, TOPIC_STUBS[topic_key]):
        return

    target_state, prompt = _BUTTON_PROMPTS[message.text]
    await state.set_state(target_state)
    await message.answer(prompt)


@router.message(StateFilter(*_MODE_HANDLERS.keys()), F.voice | F.text)
async def handle_mode_content(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    current = await state.get_state()
    handler = next((h for s, h in _MODE_HANDLERS.items() if s.state == current), None)
    await state.clear()
    if handler is None:
        return

    # Повторная проверка темы (Phase 82) — см. комментарий у
    # handle_mode_button/_STATE_TOPIC_KEYS.
    topic_key = _STATE_TOPIC_KEYS.get(current)
    if topic_key is not None:
        topic_id = await get_or_create_topic(message.bot, message.from_user.id, topic_key)
        if not await ensure_in_topic(message, topic_id, TOPIC_STUBS[topic_key]):
            return

    text = await extract_text(message)
    if not text:
        return
    await handler(message, text)


@router.message(StateFilter(ModeStates.question), F.text | F.voice | F.photo | F.document)
async def handle_question_button(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    # Повторная проверка темы (Phase 81) — см. комментарий у
    # handle_mode_button выше.
    topic_id = await get_or_create_topic(message.bot, message.from_user.id, "questions")
    if not await ensure_in_topic(message, topic_id, TOPIC_STUBS["questions"]):
        await state.clear()
        return

    await state.clear()
    await handle_question_input(message)


# Повторяющиеся задачи (Phase 73) — свои два хендлера, не через
# generic _MODE_HANDLERS/handle_mode_content выше: тот безусловно чистит
# state ДО вызова хендлера, а здесь хендлер сам решает, очистить state
# (правило создано или откровенно не разобрать) или перевести в
# RecurringClarificationStates.awaiting_answer (Claude задал уточняющий
# вопрос) — состояние нужно живым ПОСЛЕ вызова.
@router.message(StateFilter(ModeStates.recurring), F.voice | F.text)
async def handle_recurring_button(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    # Повторная проверка темы (Phase 82) — см. комментарий у
    # handle_mode_button выше; "Повторяющаяся" делит тему "Задачи".
    topic_id = await get_or_create_topic(message.bot, message.from_user.id, "tasks")
    if not await ensure_in_topic(message, topic_id, TOPIC_STUBS["tasks"]):
        await state.clear()
        return

    text = await extract_text(message)
    if not text:
        return
    await handle_new_recurring_task(message, text, state)


@router.message(StateFilter(RecurringClarificationStates.awaiting_answer), F.voice | F.text)
async def handle_recurring_clarification_button(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    # Тот же уточняющий диалог продолжается — если он начался в теме
    # "Задачи" (см. handle_recurring_button выше), ответ на уточнение
    # должен прийти оттуда же.
    topic_id = await get_or_create_topic(message.bot, message.from_user.id, "tasks")
    if not await ensure_in_topic(message, topic_id, TOPIC_STUBS["tasks"]):
        await state.clear()
        return

    text = await extract_text(message)
    if not text:
        return
    await handle_recurring_clarification_answer(message, text, state)
