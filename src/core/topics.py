"""Темы Telegram (Bot API 9.3, "Threaded Mode" — темы теперь работают и
в личных чатах, не только в супергруппах) — постепенный перевод
сценариев бота в отдельные темы внутри одного личного чата, вместо
одной сплошной ленты.

Phase 81 — "Вопросы" первой. Phase 82 — ещё три группы, каждая на
несколько сценариев сразу (как попросили): "Задачи" (задачи, напоминалки,
повторяющиеся), "Заметки", "Планирование" (дневник, финансы, цели,
привычки). Команды (/reminders, /nag, /timezone и т.п.) НЕ переезжают —
работают из любого места чата, как и раньше; переезжает только сам
разговорный ввод (кнопки-режимы, свободный текст/голос, документ с
CSV-выпиской) и исходящие сообщения фоновых джоб, которые сами
инициируют разговор (дневник вечером, опрос целей, напоминание про
привычки/выписку).

Требует один раз включённый в @BotFather "Threaded Mode" для этого бота
— без этого create_forum_topic ответит ошибкой Bad Request. Настройка
бот-wide (влияет на все личные чаты бота со всеми авторизованными
пользователями разом, не включается отдельно на каждого)."""

from aiogram import Bot
from aiogram.types import Message

from src.core.user_location import save_topic_id, topic_id

TOPIC_NAMES = {
    "questions": "Вопросы",
    "tasks": "Задачи",
    "notes": "Заметки",
    "planning": "Планирование",
}

TOPIC_STUBS = {
    "questions": (
        "❓ Вопросы теперь в отдельной теме — открой «Вопросы» в списке "
        "тем этого чата и спроси там, отвечу."
    ),
    "tasks": (
        "📝 Задачи, напоминалки и повторяющиеся — теперь в теме «Задачи», открой её и напиши там."
    ),
    "notes": "🗒 Заметки — теперь в теме «Заметки», открой её и напиши там.",
    "planning": ("📔 Дневник, финансы, цели и привычки — теперь в теме «Планирование», открой её."),
}


async def get_or_create_topic(bot: Bot, user_id: int, topic_key: str) -> int:
    """id темы этого пользователя для группы сценариев topic_key. Сама
    тема — реальный объект в Telegram, создаётся один раз лениво (при
    первом обращении, откуда бы оно ни пришло) и id кэшируется в БД —
    иначе каждый вызов плодил бы новую тему вместо переиспользования уже
    созданной."""
    existing = await topic_id(user_id, topic_key)
    if existing is not None:
        return existing
    topic = await bot.create_forum_topic(chat_id=user_id, name=TOPIC_NAMES[topic_key])
    await save_topic_id(user_id, topic_key, topic.message_thread_id)
    return topic.message_thread_id


async def ensure_in_topic(message: Message, topic_id: int, stub_text: str) -> bool:
    """True — сообщение и так уже в нужной теме, обрабатывать как обычно.
    False — было не в ней (обычно General) — уже отправили заглушку
    вместо этого, вызывающая сторона должна остановиться, не обрабатывать
    сообщение дальше."""
    if message.message_thread_id == topic_id:
        return True
    await message.answer(stub_text)
    return False
