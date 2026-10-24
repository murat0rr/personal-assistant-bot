"""Команда `/widget_token` (2026-10-25) — выдаёт долгоживущий токен
для виджета на главном экране телефона (Scriptable на iOS, Tasker на
Android): вставляется один раз в конфиг виджета, дальше сам виджет
ходит за данными напрямую на `src/adapters/widget_api.py`, минуя бота.

Read-only со стороны виджета — эта команда только ВЫДАЁТ токен, сам
просмотр задач происходит на отдельном эндпоинте."""

from urllib.parse import urlparse

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.widget_token import create_widget_token

router = Router()


@router.message(Command("widget_token"))
async def handle_widget_token_command(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    if not settings.miniapp_url:
        await message.answer("Виджет не настроен — пусто MINIAPP_URL в .env.")
        return

    token = create_widget_token(message.from_user.id)
    base = urlparse(settings.miniapp_url)
    url = f"{base.scheme}://{base.netloc}/widget/today-tasks"

    # Токен — отдельным коротким сообщением (легко скопировать тапом,
    # не теряется в большом блоке инструкции ниже); повторный вызов
    # команды просто выдаёт новый, старый не инвалидируется явно.
    await message.answer(
        f"Токен для виджета (действует ~год, никому не показывай):\n`{token}`",
        parse_mode="Markdown",
    )

    scriptable_code = (
        'const token = "ВСТАВЬ_СЮДА_ТОКЕН"\n'
        f'const url = "{url}"\n\n'
        "const req = new Request(url)\n"
        'req.headers = { "Authorization": "Bearer " + token }\n'
        "const data = await req.loadJSON()\n\n"
        "const w = new ListWidget()\n"
        'w.addText("Задачи на сегодня").font = Font.boldSystemFont(14)\n'
        "if (data.tasks.length === 0) {\n"
        '  w.addText("Пусто 🎉").font = Font.systemFont(13)\n'
        "}\n"
        "data.tasks.forEach(t => {\n"
        '  const line = w.addText((t.done ? "✅ " : "⬜️ ") + t.title)\n'
        "  line.font = Font.systemFont(13)\n"
        "})\n"
        "Script.setWidget(w)\n"
        "Script.complete()"
    )

    await message.answer(
        "*iOS (Scriptable, бесплатно, без App Store-подписки):*\n"
        "1. Установи приложение Scriptable.\n"
        "2. Создай новый скрипт, вставь код ниже (вместо "
        "«ВСТАВЬ\\_СЮДА\\_ТОКЕН» — токен из сообщения выше).\n"
        f"```\n{scriptable_code}\n```\n"
        "3. На главном экране — долгое нажатие → «+» → выбери "
        "Scriptable → выбери свой скрипт как виджет.\n\n"
        "*Android (Tasker, уже используется в проекте для экранного "
        "времени):*\n"
        "1. Создай профиль/задачу с действием HTTP Request — "
        f"метод GET, URL `{url}`, заголовок "
        "`Authorization: Bearer <токен>`.\n"
        "2. Ответ (JSON) положи в переменную и достань заголовки задач "
        "функцией `%http_data.tasks[].title` (Tasker умеет JSON-пути "
        "прямо в переменных) — или через плагин AutoTools JSON Read, "
        "если нужно показать done/не done отдельно.\n"
        "3. Выведи результат в Scene и прикрепи Scene как виджет на "
        "главный экран (Tasker → Scene → «Add to home screen»).\n\n"
        "Токен не отмечает задачи выполненными — только показывает "
        "список, это сознательное ограничение (виджет read-only).",
        parse_mode="Markdown",
    )
