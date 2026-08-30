from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from src.core.auth import is_authorized
from src.core.message_text import extract_text
from src.handlers.f1_task_note import handle_task_note
from src.handlers.f_notes import handle_note
from src.handlers.f_question import handle_question_input
from src.handlers.f_recurring import handle_new_recurring_task
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

# ModeStates.question сюда не входит — у него свой хендлер (handle_question_button
# ниже): нужен мультимодальный ввод (фото/PDF) и мгновенный ack, который
# generic-путь через extract_text не покрывает.
_MODE_HANDLERS = {
    ModeStates.task: handle_task_note,
    ModeStates.note: handle_note,
    ModeStates.reminder: handle_new_reminder,
    ModeStates.recurring: handle_new_recurring_task,
}


@router.message(F.text.in_(_BUTTON_PROMPTS.keys()))
async def handle_mode_button(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    assert message.text is not None
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

    text = await extract_text(message)
    if not text:
        return
    await handler(message, text)


@router.message(StateFilter(ModeStates.question), F.text | F.voice | F.photo | F.document)
async def handle_question_button(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    await state.clear()
    await handle_question_input(message)
