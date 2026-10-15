import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.core.auth import is_authorized
from src.core.chat_watch import (
    ingest_message,
    list_watched_chats,
    register_watched_chat,
    remove_watched_chat,
    set_watched_chat_enabled,
    update_watched_chat_prompt,
)
from src.core.message_text import extract_text

logger = logging.getLogger(__name__)

router = Router()

_PROMPT_HINT = (
    "Напиши критерий для этого чата — что считать полезным. Например: "
    "«вытаскивай решения/факты/ссылки в заметки, пропускай болтовню; "
    "явная просьба/обещание — в задачу»."
)

# Быстрые шаблоны (Phase 99) — вместо печати текста с нуля каждый раз.
_TEMPLATE_ALL = (
    "Каждый пост сохраняй как отдельную заметку целиком, без фильтрации "
    "и оценки полезности. Задачи создавай только если в посте явно "
    "что-то просят сделать."
)
_TEMPLATE_JOBS = (
    "Это канал с вакансиями. Сверяясь с профилем пользователя ниже (если "
    "он есть), сохраняй в заметки только вакансии, которые реально "
    "подходят под его цели и навыки; для подходящей вакансии "
    "дополнительно создай задачу «откликнуться на ...». Остальное "
    "пропускай."
)
_TEMPLATES = {"all": _TEMPLATE_ALL, "jobs": _TEMPLATE_JOBS}


class ChatWatchStates(StatesGroup):
    awaiting_forward = State()
    awaiting_prompt = State()
    awaiting_new_prompt = State()


def _parse_id_arg(message: Message) -> int | None:
    assert message.text is not None
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    try:
        return int(parts[1].strip())
    except ValueError:
        return None


def _format_chat_line(chat: dict) -> str:
    status = "вкл" if chat["enabled"] else "выкл"
    prompt_preview = chat["custom_prompt"][:60]
    return f"#{chat['id']} {chat['title']} ({status}) — {prompt_preview}"


def _template_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Все посты — в заметки", callback_data="watchtpl:all")],
            [
                InlineKeyboardButton(
                    text="💼 Вакансии под мой профиль", callback_data="watchtpl:jobs"
                )
            ],
            [InlineKeyboardButton(text="🎯 Свой критерий", callback_data="watchtpl:custom")],
        ]
    )


async def _resolve_chat_type(bot, chat_id: int) -> str | None:
    """Проверяет, что бот реально добавлен в канал (админом) или группу
    (участником) — естественная замена MTProto-резолву из Phase 87.
    None — бот туда не добавлен или чат недоступен."""
    try:
        chat = await bot.get_chat(chat_id)
        member = await bot.get_chat_member(chat_id, bot.id)
    except TelegramBadRequest:
        return None
    if member.status in ("left", "kicked"):
        return None
    if chat.type == "channel":
        return "channel" if member.status == "administrator" else None
    if chat.type in ("group", "supergroup"):
        return "group"
    return None


@router.message(Command("watch_add"), F.chat.type.in_({"group", "supergroup"}))
async def handle_watch_add_in_group(message: Message, state: FSMContext) -> None:
    """/watch_add, отправленная прямо в группе, куда уже добавлен бот —
    chat_id берётся сразу, без форварда (быстрый путь для групп)."""
    if not message.from_user or not await is_authorized(message.from_user.id):
        return
    chat_type = await _resolve_chat_type(message.bot, message.chat.id)
    if chat_type is None:
        await message.answer("Не вижу себя в этой группе — добавь бота и повтори /watch_add.")
        return
    await state.update_data(
        candidate={
            "telegram_chat_id": message.chat.id,
            "title": message.chat.title or str(message.chat.id),
            "chat_type": chat_type,
        }
    )
    await state.set_state(ChatWatchStates.awaiting_prompt)
    await message.answer(
        f"Группа: «{message.chat.title}». {_PROMPT_HINT}", reply_markup=_template_keyboard()
    )


@router.message(Command("watch_add"), F.chat.type == "private")
async def handle_watch_add(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return
    await state.set_state(ChatWatchStates.awaiting_forward)
    await message.answer(
        "Перешли сюда любой пост из канала или сообщение из группы, куда уже добавлен бот "
        "(в канал — как админа, в группу — как участника)."
    )


@router.message(StateFilter(ChatWatchStates.awaiting_forward), F.forward_from_chat)
async def handle_watch_add_forward(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    assert message.forward_from_chat is not None
    source = message.forward_from_chat
    chat_type = await _resolve_chat_type(message.bot, source.id)
    if chat_type is None:
        await state.clear()
        await message.answer(
            "Бот туда не добавлен (в канал — нужно админом, в группу — участником) "
            "или чат недоступен. Добавь бота и повтори /watch_add."
        )
        return

    await state.update_data(
        candidate={
            "telegram_chat_id": source.id,
            "title": source.title or str(source.id),
            "chat_type": chat_type,
        }
    )
    await state.set_state(ChatWatchStates.awaiting_prompt)
    await message.answer(
        f"Чат: «{source.title}». {_PROMPT_HINT}", reply_markup=_template_keyboard()
    )


@router.message(StateFilter(ChatWatchStates.awaiting_forward))
async def handle_watch_add_forward_missing(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        return
    await message.answer(
        "Это не похоже на форвард — перешли сюда пост из канала/сообщение из группы."
    )


async def _register_and_confirm(message: Message, state: FSMContext, custom_prompt: str) -> None:
    data = await state.get_data()
    candidate = data.get("candidate")
    await state.clear()
    if not candidate or not message.from_user:
        return
    try:
        await register_watched_chat(
            message.from_user.id,
            candidate["telegram_chat_id"],
            candidate["title"],
            candidate["chat_type"],
            custom_prompt,
        )
    except Exception:
        logger.exception("Не удалось зарегистрировать наблюдение за чатом %r", candidate)
        await message.answer("Не получилось зарегистрировать чат, попробуй ещё раз.")
        return
    await message.answer(f"Готово — наблюдаю за «{candidate['title']}» с этим критерием.")


@router.callback_query(F.data.startswith("watchtpl:"))
async def handle_watch_template(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if not callback.data or not isinstance(callback.message, Message):
        return

    key = callback.data.split(":", 1)[1]
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    if key == "custom":
        await state.set_state(ChatWatchStates.awaiting_prompt)
        await callback.message.answer("Напиши свой критерий текстом.")
        return

    template = _TEMPLATES.get(key)
    if template is None:
        return
    await _register_and_confirm(callback.message, state, template)


@router.message(StateFilter(ChatWatchStates.awaiting_prompt), F.voice | F.text)
async def handle_watch_prompt_input(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return
    text = await extract_text(message)
    if not text:
        return
    await _register_and_confirm(message, state, text)


@router.message(Command("watch_list"))
async def handle_watch_list(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    chats = await list_watched_chats(message.from_user.id)
    if not chats:
        await message.answer("Пока нет наблюдаемых чатов — /watch_add, чтобы добавить.")
        return
    await message.answer("\n".join(_format_chat_line(c) for c in chats))


@router.message(Command("watch_toggle"))
async def handle_watch_toggle(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    chat_id = _parse_id_arg(message)
    if chat_id is None:
        await message.answer("Укажи id: /watch_toggle 3 (см. /watch_list).")
        return

    chats = await list_watched_chats(message.from_user.id)
    current = next((c for c in chats if c["id"] == chat_id), None)
    if current is None:
        await message.answer("Это уже неактуально — такого чата нет в списке.")
        return

    updated = await set_watched_chat_enabled(chat_id, message.from_user.id, not current["enabled"])
    if updated is None:
        await message.answer("Это уже неактуально.")
        return
    status = "вкл" if updated["enabled"] else "выкл"
    await message.answer(f"«{updated['title']}» — теперь {status}.")


@router.message(Command("watch_prompt"))
async def handle_watch_prompt_edit(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    chat_id = _parse_id_arg(message)
    if chat_id is None:
        await message.answer("Укажи id: /watch_prompt 3 (см. /watch_list).")
        return

    await state.update_data(watched_chat_id=chat_id)
    await state.set_state(ChatWatchStates.awaiting_new_prompt)
    await message.answer(_PROMPT_HINT)


@router.message(StateFilter(ChatWatchStates.awaiting_new_prompt), F.voice | F.text)
async def handle_watch_new_prompt_input(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    data = await state.get_data()
    chat_id = data.get("watched_chat_id")
    await state.clear()
    text = await extract_text(message)
    if not text or chat_id is None:
        return

    updated = await update_watched_chat_prompt(chat_id, message.from_user.id, text)
    if updated is None:
        await message.answer("Это уже неактуально — такого чата нет в списке.")
        return
    await message.answer(f"Критерий для «{updated['title']}» обновлён.")


@router.message(Command("watch_remove"))
async def handle_watch_remove(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    chat_id = _parse_id_arg(message)
    if chat_id is None:
        await message.answer("Укажи id: /watch_remove 3 (см. /watch_list).")
        return

    removed = await remove_watched_chat(chat_id, message.from_user.id)
    if not removed:
        await message.answer("Это уже неактуально.")
        return
    await message.answer("Снято с наблюдения, буфер сообщений тоже удалён.")


# ---- Приём сообщений (замена MTProto-листенера Phase 87) -----------------


@router.channel_post()
async def handle_channel_post(message: Message) -> None:
    """Посты канала, где бот — админ. У Message нет from_user в
    channel_post — отправитель как таковой не нужен, подписываем
    названием канала."""
    text = await extract_text(message)
    if not text:
        return
    try:
        await ingest_message(
            telegram_chat_id=message.chat.id,
            sender_telegram_id=None,
            sender_display_name=message.chat.title or "канал",
            text=text,
            sent_at=message.date,
        )
    except Exception:
        logger.exception("Не удалось обработать пост наблюдаемого канала")


@router.message(F.chat.type.in_({"group", "supergroup"}), StateFilter(None))
async def handle_group_message(message: Message) -> None:
    """Сообщения группы — фильтрация "это наблюдаемый чат?" внутри
    ingest_message (запрос в БД, no-op если группа не зарегистрирована).
    StateFilter(None) — не перехватывать сообщения, пока пользователь
    в середине диалога регистрации (awaiting_prompt и т.п.) в этой же
    группе."""
    if message.text and message.text.startswith("/"):
        return  # команды разбираются своими хендлерами выше
    text = await extract_text(message)
    if not text or not message.from_user:
        return
    try:
        await ingest_message(
            telegram_chat_id=message.chat.id,
            sender_telegram_id=message.from_user.id,
            sender_display_name=message.from_user.full_name,
            text=text,
            sent_at=message.date,
        )
    except Exception:
        logger.exception("Не удалось обработать сообщение наблюдаемой группы")
