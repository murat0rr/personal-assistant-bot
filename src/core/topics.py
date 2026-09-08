"""Темы Telegram (Bot API 9.3, "Threaded Mode" — темы теперь работают и
в личных чатах, не только в супергруппах) — постепенный перевод
сценариев бота в отдельные темы внутри одного личного чата, вместо
одной сплошной ленты (Phase 81, фидбек).

Первый шаг — только "Вопросы": обработка вопроса возможна, только если
сообщение реально пришло из этой темы. В любом другом месте чата
(обычно — General, вне тем) бот присылает заглушку вместо ответа —
ensure_in_topic ниже, общий примитив для будущих шагов того же рода
(дневник, финансы и т.п.), не только вопросов.

Требует один раз включённый в @BotFather "Threaded Mode" для этого бота
— без этого create_forum_topic ответит ошибкой Bad Request. Настройка
бот-wide (влияет на все личные чаты бота со всеми авторизованными
пользователями разом, не включается отдельно на каждого)."""

from aiogram import Bot
from aiogram.types import Message

from src.core.user_location import questions_topic_id, save_questions_topic_id

QUESTIONS_TOPIC_NAME = "Вопросы"
QUESTIONS_STUB_TEXT = (
    "❓ Вопросы теперь в отдельной теме — открой «Вопросы» в списке тем "
    "этого чата и спроси там, отвечу."
)


async def get_or_create_questions_topic(bot: Bot, user_id: int) -> int:
    """id темы "Вопросы" этого пользователя. Сама тема — реальный объект
    в Telegram, создаётся один раз лениво (при первом вопросе, откуда бы
    он ни пришёл) и id кэшируется в БД — иначе каждый вызов плодил бы
    новую тему вместо переиспользования уже созданной."""
    existing = await questions_topic_id(user_id)
    if existing is not None:
        return existing
    topic = await bot.create_forum_topic(chat_id=user_id, name=QUESTIONS_TOPIC_NAME)
    await save_questions_topic_id(user_id, topic.message_thread_id)
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
