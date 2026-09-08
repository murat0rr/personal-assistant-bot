"""Команда /set_day_task (Phase 80) — прототип на новом Rich Message API
Telegram (Bot API 10.3, 25 августа 2026): один список задач на сегодня
ОДНИМ сообщением, где каждая задача — сама кнопка (RichBlockButtons).
Тап переключает done прямо в сообщении: текст зачёркивается
(RichTextStrikethrough) и цвет кнопки меняется (ButtonStyle) — без
отдельной клавиатуры под текстом, всё внутри самого сообщения.

Явный прототип по прямой просьбе — минимум обвеса, максимум "потрогать
своими руками, как это вообще выглядит". Не встроено ни в один из
обычных сценариев бота (mode_buttons.py и т.п.), совсем отдельная
команда.

"Обновляется, если задачи появились" — на каждый тап по любой кнопке
список перечитывается из БД заново целиком, а не просто щёлкает одна
задача — так сообщение самолечится, если за это время где-то ещё
(Mini App, голосом) появилась/пропала другая задача на сегодня.
Повторный /set_day_task редактирует ТО ЖЕ сообщение вместо того, чтобы
плодить новое — ссылка на него живёт в FSM-данных пользователя (тот же
приём без именованного состояния, что уже есть в f_morning_advice.py),
не в отдельной таблице — специально не заводил под это миграцию ради
разового прототипа.
"""

import logging

from aiogram import F, Router
from aiogram.enums import ButtonStyle
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichMessage,
    Message,
    RichMessageButton,
    RichTextStrikethrough,
)
from sqlalchemy import select

from src.core.auth import is_authorized
from src.core.db import async_session
from src.core.user_location import user_today
from src.models.task import Task

logger = logging.getLogger(__name__)

router = Router()

_FSM_KEY_CHAT = "day_task_chat_id"
_FSM_KEY_MESSAGE = "day_task_message_id"


async def _load_today_tasks(user_id: int) -> list[Task]:
    today = await user_today(user_id)
    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .where(
                Task.archived.is_(False),
                Task.user_id == user_id,
                Task.due_date.is_not(None),
            )
            .order_by(Task.sort_order)
        )
        tasks = result.scalars().all()
    return [t for t in tasks if t.due_date.date() == today]


def _build_rich_message(tasks: list[Task]) -> InputRichMessage:
    blocks: list = [
        InputRichBlockSectionHeading(text="Задачи на сегодня", size=2),
    ]
    if not tasks:
        blocks.append(InputRichBlockParagraph(text="Пусто — на сегодня ничего не стоит."))
        return InputRichMessage(blocks=blocks)

    for task in tasks:
        button = RichMessageButton(
            text=RichTextStrikethrough(text=task.title) if task.done else task.title,
            style=ButtonStyle.SUCCESS if task.done else ButtonStyle.PRIMARY,
            callback_data=f"daytask_toggle:{task.id}",
        )
        blocks.append(InputRichBlockButtons(buttons=[button]))
    return InputRichMessage(blocks=blocks)


async def _render(user_id: int) -> InputRichMessage:
    tasks = await _load_today_tasks(user_id)
    return _build_rich_message(tasks)


@router.message(Command("set_day_task"))
async def handle_set_day_task(message: Message, state: FSMContext) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    user_id = message.from_user.id
    rich_message = await _render(user_id)

    data = await state.get_data()
    chat_id = data.get(_FSM_KEY_CHAT)
    message_id = data.get(_FSM_KEY_MESSAGE)

    # Повторный вызов команды — правим уже существующее сообщение, а не
    # плодим новое; если его больше нет (удалено вручную, чат другой) —
    # тихо откатываемся на отправку нового.
    if chat_id is not None and message_id is not None:
        try:
            await message.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, rich_message=rich_message
            )
            return
        except Exception:
            logger.info("Не удалось отредактировать старое сообщение /set_day_task — шлю новое")

    sent = await message.bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_message)
    await state.update_data(**{_FSM_KEY_CHAT: sent.chat.id, _FSM_KEY_MESSAGE: sent.message_id})


@router.callback_query(F.data.startswith("daytask_toggle:"))
async def handle_toggle_task(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if not callback.data or not isinstance(callback.message, Message):
        return

    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer("Задача не найдена — возможно, уже удалена", show_alert=True)
            return
        task.done = not task.done
        await session.commit()

    # Перечитываем ВЕСЬ список заново (не только эту задачу) — заодно
    # подхватит любые изменения, случившиеся где-то ещё с прошлой
    # отрисовки (см. докстринг модуля).
    rich_message = await _render(user_id)
    await callback.message.bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        rich_message=rich_message,
    )
    await callback.answer()
