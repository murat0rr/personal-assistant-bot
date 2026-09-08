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

Живое обновление (Phase 80, довесок по фидбеку живой проверки — "написал
добавь задачу, в сообщении не появилась, пока не набрал команду заново")
— НЕ полагается только на "перечитать при следующем тапе": как только
где угодно меняется что-то, что могло затронуть сегодняшний список
(создание/архивация задачи, смена даты, смена статуса — из бота ИЛИ из
Mini App, отдельный процесс api), вызывающая сторона зовёт
refresh_day_task_message(bot, user_id) — она молча no-op, если для этого
пользователя ещё ни разу не отправляли /set_day_task. Ссылка на
последнее отправленное сообщение — в Redis (settings.redis_url), не в
FSM-хранилище: FSMContext привязан к конкретному Dispatcher/процессу, а
обновлять сообщение нужно и из процесса api (Mini App), с которым общей
памяти нет — тот же приём, что уже решает эту же проблему у
core/login_codes.py (код входа рождается в bot, проверяется в api).
Разовый прототип — своя таблица в Postgres ради этого была бы
избыточна, TTL сам почистит забытые ссылки."""

import logging

import redis.asyncio as redis
from aiogram import Bot, F, Router
from aiogram.enums import ButtonStyle
from aiogram.filters import Command
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
from src.core.config import settings
from src.core.db import async_session
from src.core.user_location import user_today
from src.models.task import Task

logger = logging.getLogger(__name__)

router = Router()

# Тот же TTL-подход, что у остальных Redis-ключей проекта (login_codes.py)
# — если сообщением ни разу не пользовались неделю, ссылка сама протухнет,
# не нужно отдельно чистить.
_REDIS_TTL_SECONDS = 7 * 24 * 60 * 60
_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def _load_message_ref(user_id: int) -> tuple[int, int] | None:
    raw = await _get_redis().get(f"daytask:message:{user_id}")
    if not raw:
        return None
    chat_id_str, message_id_str = raw.split(":")
    return int(chat_id_str), int(message_id_str)


async def _save_message_ref(user_id: int, chat_id: int, message_id: int) -> None:
    await _get_redis().set(
        f"daytask:message:{user_id}", f"{chat_id}:{message_id}", ex=_REDIS_TTL_SECONDS
    )


async def _forget_message_ref(user_id: int) -> None:
    await _get_redis().delete(f"daytask:message:{user_id}")


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


async def refresh_day_task_message(bot: Bot, user_id: int) -> None:
    """Перерисовывает уже отправленное /set_day_task сообщение этого
    пользователя, если оно есть — вызывать после ЛЮБОЙ правки задачи,
    которая могла затронуть сегодняшний список (создание, архивация,
    смена даты/статуса), откуда угодно: из бота (f1_task_note.py) или
    из Mini App (adapters/api.py, через core/bot_client.py::get_bot()).
    Тихий no-op, если пользователь ни разу не вызывал /set_day_task —
    это не баг, а нормальное "фичей не пользовались", как и у похожих
    необязательных уведомлений в проекте (см. record_task_completion в
    f_task_nag.py)."""
    ref = await _load_message_ref(user_id)
    if ref is None:
        return
    chat_id, message_id = ref
    rich_message = await _render(user_id)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, rich_message=rich_message
        )
    except Exception:
        # Сообщение могли удалить руками, оно могло устареть и т.п. —
        # не должно ронять тот реальный вызов (создание/правку задачи),
        # из-за которого мы сюда попали. Забываем ссылку, чтобы не
        # пытаться её же на каждую следующую правку — следующий
        # /set_day_task заведёт новую.
        logger.info("Не удалось обновить /set_day_task сообщение (%s) — забываю ссылку", user_id)
        await _forget_message_ref(user_id)


@router.message(Command("set_day_task"))
async def handle_set_day_task(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    user_id = message.from_user.id
    rich_message = await _render(user_id)

    ref = await _load_message_ref(user_id)

    # Повторный вызов команды — правим уже существующее сообщение, а не
    # плодим новое; если его больше нет (удалено вручную, чат другой) —
    # тихо откатываемся на отправку нового.
    if ref is not None:
        chat_id, message_id = ref
        try:
            await message.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, rich_message=rich_message
            )
            return
        except Exception:
            logger.info("Не удалось отредактировать старое сообщение /set_day_task — шлю новое")

    sent = await message.bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_message)
    await _save_message_ref(user_id, sent.chat.id, sent.message_id)


@router.callback_query(F.data.startswith("daytask_toggle:"))
async def handle_toggle_task(callback: CallbackQuery) -> None:
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
    # отрисовки.
    rich_message = await _render(user_id)
    await callback.message.bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        rich_message=rich_message,
    )
    await callback.answer()
