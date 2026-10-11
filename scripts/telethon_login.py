"""Разовый интерактивный логин MTProto-клиента владельца (Phase 87,
наблюдение за внешними чатами). Запускать ВРУЧНУЮ на своей машине:

    uv run python scripts/telethon_login.py

Номер телефона и код подтверждения вводятся интерактивно в терминал —
это НЕ автоматизируется, не встраивается в старт основного приложения
и никогда не должно запускаться из CI/облачного агента. Результат —
строка сессии, которую нужно вставить в .env как TELETHON_SESSION_STRING
(полный доступ к личному аккаунту — хранить только там, не коммитить).

api_id/api_hash — с https://my.telegram.org, раздел "API development
tools" (это НЕ TELEGRAM_BOT_TOKEN, обычное приложение, тип любой)."""

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    api_id = int(input("TELETHON_API_ID: ").strip())
    api_hash = input("TELETHON_API_HASH: ").strip()
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start()
        print("\nСтрока сессии — вставить в .env как TELETHON_SESSION_STRING:\n")
        print(client.session.save())


if __name__ == "__main__":
    asyncio.run(main())
