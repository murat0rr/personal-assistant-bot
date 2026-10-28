import logging
import random
import time
from datetime import date, datetime, timedelta

import redis.asyncio as redis
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from src.core.auth import is_authorized
from src.core.config import settings
from src.core.db import async_session
from src.core.user_location import user_today
from src.core.user_profile import get_profile_summary
from src.handlers.f_set_day_task import refresh_day_task_message
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


def _fsm_state(bot: Bot, storage: BaseStorage, user_id: int) -> FSMContext:
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


async def send_morning_advice(bot: Bot, storage: BaseStorage, user_id: int, today: date) -> None:
    """Утренний совет (Phase 23) — отдельное сообщение вслед за
    дайджестом: смотрит на вчера/сегодня/инбокс, предлагает подтянуть
    что-то из инбокса на сегодня с учётом нагрузки. Кнопки "Добавить"/
    "Не сегодня" под сообщением — сами task_id хранятся в FSM-данных
    (не в callback_data — список id может не влезть в лимит Telegram)."""
    yesterday = today - timedelta(days=1)

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.archived.is_(False), Task.done.is_(False), Task.user_id == user_id
            )
        )
        tasks = result.scalars().all()

    # Веса сложности (фидбек 2026-10-24) — тащим вместе с title, чтобы
    # suggest_tasks_for_today мог балансировать нагрузку не только по
    # объёму, но и по типу усилия; у задач без весов (весь бэклог до
    # этой фазы) все три ключа будут None — деградация без данных
    # внутри suggest_tasks_for_today (_format_load_suffix).
    def _to_item(t: Task) -> dict:
        return {
            "id": t.id,
            "title": t.title,
            "physical_load": t.physical_load,
            "mental_load": t.mental_load,
            "emotional_load": t.emotional_load,
        }

    overdue_items = [
        _to_item(t) for t in tasks if t.due_date is not None and t.due_date.date() == yesterday
    ]
    today_items = [
        _to_item(t) for t in tasks if t.due_date is not None and t.due_date.date() == today
    ]
    inbox_items = [_to_item(t) for t in tasks if t.due_date is None]

    if not inbox_items:
        return

    try:
        profile_summary = await get_profile_summary(user_id)
        suggested_ids = await suggest_tasks_for_today(
            overdue_items, today_items, inbox_items, today, profile_summary
        )
    except Exception:
        logger.exception("Не удалось получить совет по задачам на сегодня")
        return
    if not suggested_ids:
        return

    by_id = {item["id"]: item["title"] for item in inbox_items}
    lines = "\n".join(f"— {by_id[i]}" for i in suggested_ids if i in by_id)
    if not lines:
        return

    state = _fsm_state(bot, storage, user_id)
    await state.update_data(advice_task_ids=suggested_ids)
    await bot.send_message(
        chat_id=user_id,
        text=f"💡 Из инбокса на сегодня стоит подтянуть:\n{lines}",
        reply_markup=_ADVICE_KEYBOARD,
    )


# Похвала при закрытии дня (фидбек 2026-10-24) — несколько вариантов,
# чтобы не повторялось буква в букву каждый раз (тот же мотив, что у
# вариативных подтверждений в других фичах проекта).
_PRAISE_TEXTS = (
    "Все задачи на сегодня закрыты — отличная работа! 🎉",
    "День закрыт, всё сделано. Красота! 👏",
    "Чисто — ни одной незакрытой задачи на сегодня. Молодец!",
    "Сегодняшний список пуст — ты справился со всем. 🙌",
)
# Anti-спам guard — максимум одна похвала в день на пользователя, тот же
# приём по духу, что daytask:message:{user_id} в f_set_day_task.py, но
# про сам факт похвалы, не про сообщение; ключ несёт дату — завтрашний
# день естественно получит новый ключ, TTL с запасом, не точно до
# полуночи (не критично, какая-то лишняя минута-другая не страшна).
_PRAISE_GUARD_TTL_SECONDS = 36 * 60 * 60
_praise_redis: redis.Redis | None = None


def _get_praise_redis() -> redis.Redis:
    global _praise_redis
    if _praise_redis is None:
        _praise_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _praise_redis


async def maybe_praise_closed_day(
    bot: Bot, storage: BaseStorage, user_id: int, toggled_due_date: date | None
) -> None:
    """Вызывается из ЛЮБОГО места, где задача переходит в done=True
    (сейчас — f_set_day_task.py::handle_toggle_task и
    adapters/api.py::mark_task_done, единственные два места, где
    Task.done меняется) — если это закрыло ВЕСЬ список на СЕГОДНЯ
    (переход "было хоть что-то невыполненное -> стало 0", не просто
    "пусто с утра" — для этого нужна хотя бы одна toggled-в-done задача
    с due_date сегодня, что уже гарантирует вызывающая сторона), хвалит
    и сразу переиспользует send_morning_advice (тот же механизм, что у
    утренней рассылки, просто с другим триггером) — не дублирует его
    логику. Тихий no-op, если закрытая задача не на сегодня, или
    сегодня уже хвалили (anti-спам guard)."""
    if toggled_due_date is None:
        return
    today = await user_today(user_id)
    if toggled_due_date != today:
        return

    guard_key = f"praise:shown:{user_id}:{today.isoformat()}"
    if await _get_praise_redis().get(guard_key):
        return

    async with async_session() as session:
        result = await session.execute(
            select(Task.due_date).where(
                Task.user_id == user_id, Task.archived.is_(False), Task.done.is_(False)
            )
        )
        remaining_dates = result.scalars().all()
    if any(d is not None and d.date() == today for d in remaining_dates):
        return  # на сегодня остались другие невыполненные задачи — день не закрыт

    await _get_praise_redis().set(guard_key, "1", ex=_PRAISE_GUARD_TTL_SECONDS)
    await bot.send_message(chat_id=user_id, text=random.choice(_PRAISE_TEXTS))
    try:
        await send_morning_advice(bot, storage, user_id, today)
    except Exception:
        logger.exception("Не удалось предложить что-то ещё после похвалы за закрытый день")


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

    today = await user_today(callback.from_user.id)
    due = datetime.combine(today, datetime.min.time())
    async with async_session() as session:
        for task_id in task_ids:
            task = await session.get(Task, task_id)
            if task is None or task.due_date is not None or task.user_id != callback.from_user.id:
                continue
            task.due_date = due
            task.sort_order = time.time()
        await session.commit()

    try:
        await refresh_day_task_message(callback.bot, callback.from_user.id)
    except Exception:
        logger.exception("Не удалось обновить /day_tasks после принятия совета")

    await callback.answer("Добавил на сегодня")
    await callback.message.answer("Готово, добавил в сегодняшний список.")
