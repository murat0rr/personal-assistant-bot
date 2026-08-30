import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.db import async_session
from src.integrations.claude_client import suggest_tasks_for_today
from src.models.task import Task

logger = logging.getLogger(__name__)

router = Router()

_ADVICE_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Добавить", callback_data="advice:accept"),
            InlineKeyboardButton(text="Не сегодня", callback_data="advice:skip"),
        ]
    ]
)


def _fsm_state(bot: Bot, storage: BaseStorage) -> FSMContext:
    key = StorageKey(
        bot_id=bot.id,
        chat_id=settings.telegram_user_id,
        user_id=settings.telegram_user_id,
    )
    return FSMContext(storage=storage, key=key)


async def send_morning_advice(bot: Bot, storage: BaseStorage) -> None:
    """Утренний совет (Phase 23) — отдельное сообщение вслед за
    дайджестом: смотрит на вчера/сегодня/инбокс, предлагает подтянуть
    что-то из инбокса на сегодня с учётом нагрузки. Кнопки "Добавить"/
    "Не сегодня" под сообщением — сами task_id хранятся в FSM-данных
    (не в callback_data — список id может не влезть в лимит Telegram)."""
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.archived.is_(False), Task.done.is_(False))
        )
        tasks = result.scalars().all()

    overdue_titles = [
        t.title for t in tasks if t.due_date is not None and t.due_date.date() == yesterday
    ]
    today_titles = [t.title for t in tasks if t.due_date is not None and t.due_date.date() == today]
    inbox_items = [{"id": t.id, "title": t.title} for t in tasks if t.due_date is None]

    if not inbox_items:
        return

    try:
        suggested_ids = await suggest_tasks_for_today(overdue_titles, today_titles, inbox_items)
    except Exception:
        logger.exception("Не удалось получить совет по задачам на сегодня")
        return
    if not suggested_ids:
        return

    by_id = {item["id"]: item["title"] for item in inbox_items}
    lines = "\n".join(f"— {by_id[i]}" for i in suggested_ids if i in by_id)
    if not lines:
        return

    state = _fsm_state(bot, storage)
    await state.update_data(advice_task_ids=suggested_ids)
    await bot.send_message(
        chat_id=settings.telegram_user_id,
        text=f"💡 Из инбокса на сегодня стоит подтянуть:\n{lines}",
        reply_markup=_ADVICE_KEYBOARD,
    )


@router.callback_query(F.data.startswith("advice:"))
async def handle_advice_button(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if (
        not callback.data
        or not isinstance(callback.message, Message)
        or callback.message.bot is None
    ):
        return

    data = await state.get_data()
    task_ids = data.get("advice_task_ids")
    action = callback.data.removeprefix("advice:")

    if not task_ids:
        await callback.answer("Это уже неактуально", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await state.update_data(advice_task_ids=None)

    if action == "skip":
        await callback.answer("Ладно, не сегодня")
        return

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    due = datetime.combine(today, datetime.min.time())
    async with async_session() as session:
        for task_id in task_ids:
            task = await session.get(Task, task_id)
            if task is None or task.due_date is not None:
                continue
            task.due_date = due
            task.sort_order = time.time()
        await session.commit()

    await callback.answer("Добавил на сегодня")
    await callback.message.answer("Готово, добавил в сегодняшний список.")
