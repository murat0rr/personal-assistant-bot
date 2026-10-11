"""MTProto-клиент под личным аккаунтом владельца (Phase 87) — наблюдение
за внешними чатами (личные переписки с другими людьми, чужие группы),
куда бота как Bot API не добавить. Это единственное место в приложении
(кроме scripts/telethon_login.py, который не запускается автоматически),
где конструируется TelegramClient.

СТРУКТУРНОЕ ограничение, не "обещанное": этот модуль не импортирует и не
вызывает ни одного write-метода Telethon (send_message,
send_read_acknowledge, edit_message, delete_messages, реакции и т.п.) —
убедиться в этом достаточно просмотром файла, не нужно доверять ревью
логики вызовов. Любое действие, видимое в Телеграме (уведомление
владельцу), идёт только через существующего бота (core/bot_client.py),
никогда через этот клиент."""

from collections.abc import Awaitable, Callable
from typing import Any

from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.custom.dialog import Dialog

from src.core.config import settings

_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    global _client
    if _client is None:
        _client = TelegramClient(
            StringSession(settings.telethon_session_string),
            settings.telethon_api_id,
            settings.telethon_api_hash,
        )
    return _client


async def start() -> None:
    """Подключает клиент на уже готовой сессии (см. scripts/telethon_login.py
    — интерактивный логин сюда не встроен и не может быть встроен).
    Вызывается один раз из adapters/telegram_bot.py::main(), только если
    TELETHON_SESSION_STRING задан."""
    client = get_client()
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "TELETHON_SESSION_STRING недействителен или просрочен — "
            "перегенерировать через scripts/telethon_login.py"
        )


def _chat_type_of(entity: Any) -> str:
    type_name = type(entity).__name__
    if type_name == "User":
        return "user"
    if type_name == "Channel":
        return "channel" if getattr(entity, "broadcast", False) else "group"
    return "group"


def _dialog_to_dict(dialog: Dialog) -> dict:
    return {
        "telegram_chat_id": dialog.id,
        "title": dialog.name or str(dialog.id),
        "chat_type": _chat_type_of(dialog.entity),
    }


async def search_dialogs(query: str, *, limit: int = 200) -> list[dict]:
    """Только чтение: ищет среди диалогов владельца по подстроке в
    названии/username — для /watch_add в handlers/f_chat_watch.py.
    Вся телетон-специфика (типы сущностей, маркированные id) остаётся
    здесь — core/chat_watch.py получает только простые dict."""
    query_lower = query.lower()
    matches: list[dict] = []
    async for dialog in get_client().iter_dialogs(limit=limit):
        name = dialog.name or ""
        username = getattr(dialog.entity, "username", None) or ""
        if query_lower in name.lower() or query_lower in username.lower():
            matches.append(_dialog_to_dict(dialog))
    return matches


async def resolve_forwarded_chat(chat_id: int) -> dict | None:
    """Только чтение: резолвит id чата (из message.forward_from_chat.id
    на стороне бота) в {telegram_chat_id, title, chat_type} — альтернативный
    путь регистрации (форвард сообщения из чата вместо поиска по имени)."""
    try:
        entity = await get_client().get_entity(chat_id)
    except Exception:
        return None
    name = " ".join(
        filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)])
    )
    title = getattr(entity, "title", None) or name or str(chat_id)
    return {
        "telegram_chat_id": utils.get_peer_id(entity),
        "title": title,
        "chat_type": _chat_type_of(entity),
    }


def register_handler(callback: Callable[[events.NewMessage.Event], Awaitable[None]]) -> None:
    """Регистрирует callback на входящие сообщения ЛЮБОГО чата —
    фильтрация "это наблюдаемый чат?" делается внутри callback
    (core/chat_watch.py::handle_incoming_event) запросом в БД, не здесь."""
    get_client().add_event_handler(callback, events.NewMessage(incoming=True))
