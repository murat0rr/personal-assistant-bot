import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.core.chat_watch import (
    list_watched_chats,
    register_watched_chat,
    remove_watched_chat,
    resolve_forwarded_chat,
    search_watchable_chats,
    set_watched_chat_enabled,
    update_watched_chat_prompt,
)
from src.core.config import settings
from src.core.message_text import extract_text

logger = logging.getLogger(__name__)

router = Router()

_PROMPT_HINT = (
    "Напиши критерий для этого чата — что считать полезным. Например: "
    "«вытаскивай решения/факты/ссылки в заметки, пропускай болтовню; "
    'явная просьба ко мне или моя же запись "надо сделать" — в задачу».'
)
_MAX_CANDIDATES = 8


class ChatWatchStates(StatesGroup):
    awaiting_search = State()
    awaiting_prompt = State()
    awaiting_new_prompt = State()


def _is_owner(user_id: int) -> bool:
    # Владелец (не is_authorized) — регистрация наблюдения даёт доступ к
    # ЕГО личному аккаунту (MTProto-сессия), не к боту как таковому (тот
    # же принцип, что у _is_owner в f_build.py).
    return user_id == settings.telegram_user_id


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


def _candidates_keyboard(candidates: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=c["title"][:60], callback_data=f"watch:pick:{i}")]
        for i, c in enumerate(candidates[:_MAX_CANDIDATES])
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("watch_add"))
async def handle_watch_add(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    assert message.text is not None
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await _search_and_prompt(message, state, parts[1].strip())
        return

    await state.set_state(ChatWatchStates.awaiting_search)
    await message.answer(
        "Введи часть названия чата/username, или просто перешли сюда любое сообщение из него."
    )


@router.message(
    StateFilter(ChatWatchStates.awaiting_search),
    F.voice | F.text | F.forward_from_chat | F.forward_from,
)
async def handle_watch_add_input(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    if message.forward_from_chat:
        candidate = await resolve_forwarded_chat(message.forward_from_chat.id)
        if candidate is None:
            await state.clear()
            await message.answer("Не нашёл такой чат через MTProto-сессию.")
            return
        await _ask_prompt_for_candidate(message, state, candidate)
        return

    if message.forward_from:
        candidate = {
            "telegram_chat_id": message.forward_from.id,
            "title": message.forward_from.full_name,
            "chat_type": "user",
        }
        await _ask_prompt_for_candidate(message, state, candidate)
        return

    text = await extract_text(message)
    if not text:
        return
    await _search_and_prompt(message, state, text)


async def _search_and_prompt(message: Message, state: FSMContext, query: str) -> None:
    candidates = await search_watchable_chats(query)
    if not candidates:
        await state.clear()
        await message.answer(
            "Не нашёл такой чат. Это может быть переслано со скрытым отправителем "
            "(приватность собеседника) — тогда попробуй поискать по имени/username."
        )
        return
    if len(candidates) == 1:
        await _ask_prompt_for_candidate(message, state, candidates[0])
        return
    await state.update_data(candidates=candidates)
    await message.answer(
        "Нашёл несколько — выбери нужный:", reply_markup=_candidates_keyboard(candidates)
    )


async def _ask_prompt_for_candidate(message: Message, state: FSMContext, candidate: dict) -> None:
    await state.update_data(candidate=candidate)
    await state.set_state(ChatWatchStates.awaiting_prompt)
    await message.answer(f"Чат: «{candidate['title']}». {_PROMPT_HINT}")


@router.callback_query(F.data.startswith("watch:pick:"))
async def handle_watch_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_owner(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if not callback.data:
        return

    index = int(callback.data.split(":")[2])
    data = await state.get_data()
    candidates = data.get("candidates")
    if not candidates or index >= len(candidates):
        await callback.answer("Это уже неактуально", show_alert=True)
        return

    candidate = candidates[index]
    await state.update_data(candidate=candidate, candidates=None)
    await state.set_state(ChatWatchStates.awaiting_prompt)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"Чат: «{candidate['title']}». {_PROMPT_HINT}")


@router.message(StateFilter(ChatWatchStates.awaiting_prompt), F.voice | F.text)
async def handle_watch_prompt_input(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    data = await state.get_data()
    candidate = data.get("candidate")
    await state.clear()
    text = await extract_text(message)
    if not text or not candidate:
        return

    try:
        await register_watched_chat(
            message.from_user.id,
            candidate["telegram_chat_id"],
            candidate["title"],
            candidate["chat_type"],
            text,
        )
    except Exception:
        logger.exception("Не удалось зарегистрировать наблюдение за чатом %r", candidate)
        await message.answer("Не получилось зарегистрировать чат, попробуй ещё раз.")
        return

    await message.answer(f"Готово — наблюдаю за «{candidate['title']}» с этим критерием.")


@router.message(Command("watch_list"))
async def handle_watch_list(message: Message) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    chats = await list_watched_chats(message.from_user.id)
    if not chats:
        await message.answer("Пока нет наблюдаемых чатов — /watch_add, чтобы добавить.")
        return
    await message.answer("\n".join(_format_chat_line(c) for c in chats))


@router.message(Command("watch_toggle"))
async def handle_watch_toggle(message: Message) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
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
    if not message.from_user or not _is_owner(message.from_user.id):
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
    if not message.from_user or not _is_owner(message.from_user.id):
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
    if not message.from_user or not _is_owner(message.from_user.id):
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
