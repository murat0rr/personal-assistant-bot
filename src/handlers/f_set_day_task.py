"""Команда /day_tasks (Phase 80, переименовано и закреплено — фидбек
2026-10-20→22; раньше называлась /set_day_task, название путало:
звучало как разовое действие "поставить задачу на день", а не "включить
ежедневный список") — Rich Message API Telegram (Bot API 10.3): один
список задач на определённый день ОДНИМ сообщением, где каждая задача
— сама кнопка (RichBlockButtons). Тап переключает done прямо в
сообщении: текст зачёркивается (RichTextStrikethrough) и цвет кнопки
меняется (ButtonStyle) — без отдельной клавиатуры под текстом, всё
внутри самого сообщения.

Опт-ин: включается ОДИН раз командой — "нажал → с этого утра бот сам
каждый день обновляет это же закреплённое сообщение, без повторных
действий" (именно так и был сформулирован фидбек). Повторный вызов
команды вручную тоже работает (мгновенный ресинк на "сейчас"), но не
обязателен для ежедневной работы — в отличие от прошлой версии, где
автоматического утреннего обновления без разового запуска вообще не
было (и из-за этого фича выглядела нерабочей, пока её не нажали).

Закрепляется (pin_chat_message) один раз при первой отправке — дальше
остаётся закреплённым, правки существующего сообщения (edit_message_text)
статус pin не трогают, перезакреплять не нужно. При первом включении
отдельным текстовым сообщением явно объясняем, что произошло — раньше
результатом команды было ТОЛЬКО само rich-сообщение без какого-либо
"готово, теперь это работает само" подтверждения, отсюда и путаница.

Два РАЗНЫХ понятия даты здесь принципиально не путать:
- "Закреплённый день" (pinned_date, хранится вместе со ссылкой на
  сообщение) — КАКОЙ день сейчас показан. Двигается только явно: либо
  сам пользователь перевызывает /day_tasks (тогда это "сейчас"), либо
  утренняя рассылка (scheduler/jobs.py::_morning_digest →
  advance_day_task_date) — то есть ночью и рано утром, до своего часа
  рассылки, сообщение ОСОЗНАННО продолжает показывать вчерашний день,
  не "по часам" как бы предполагал user_today().
- Живое обновление ВНУТРИ уже показанного дня — полностью как раньше,
  без изменений: создание/архивация/смена статуса задачи с ЭТОЙ же
  датой (из бота или Mini App, процесс api) — вызывающая сторона зовёт
  refresh_day_task_message(bot, user_id), она перечитывает задачи
  ровно на pinned_date (не на "сегодня"), тихий no-op, если сообщение
  не заводили.

Ссылка на сообщение (chat_id, message_id, pinned_date) — в Redis
(settings.redis_url), не в FSM-хранилище: нужна и из процесса api
(Mini App), с которым общей памяти нет — тот же приём, что у
core/login_codes.py."""

import logging
from datetime import date

import redis.asyncio as redis
from aiogram import Bot, F, Router
from aiogram.enums import ButtonStyle
from aiogram.filters import Command
from aiogram.fsm.storage.base import BaseStorage
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
from src.core.tasks_cache import invalidate_tasks_cache
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


async def _load_message_ref(user_id: int) -> tuple[int, int, date | None] | None:
    raw = await _get_redis().get(f"daytask:message:{user_id}")
    if not raw:
        return None
    parts = raw.split(":")
    # len(parts) == 2 — старый формат ссылки (до pin-фичи, 2026-10-20),
    # без даты; переходный случай, пока не протухнет TTL — вызывающая
    # сторона бутстрапит дату на user_today() при первой встрече.
    pinned_date = date.fromisoformat(parts[2]) if len(parts) > 2 else None
    return int(parts[0]), int(parts[1]), pinned_date


async def _save_message_ref(user_id: int, chat_id: int, message_id: int, pinned_date: date) -> None:
    await _get_redis().set(
        f"daytask:message:{user_id}",
        f"{chat_id}:{message_id}:{pinned_date.isoformat()}",
        ex=_REDIS_TTL_SECONDS,
    )


async def _forget_message_ref(user_id: int) -> None:
    await _get_redis().delete(f"daytask:message:{user_id}")


async def _load_tasks_for_date(user_id: int, target_date: date) -> list[Task]:
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
    return [t for t in tasks if t.due_date.date() == target_date]


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


async def _render(user_id: int, target_date: date) -> InputRichMessage:
    tasks = await _load_tasks_for_date(user_id, target_date)
    return _build_rich_message(tasks)


async def refresh_day_task_message(bot: Bot, user_id: int) -> None:
    """Перерисовывает уже отправленное /day_tasks сообщение этого
    пользователя, если оно есть — вызывать после ЛЮБОЙ правки задачи,
    которая могла затронуть ПОКАЗАННЫЙ (не обязательно календарный
    "сегодня" — см. докстринг модуля) день, откуда угодно: из бота
    (f1_task_note.py) или из Mini App (adapters/api.py, через
    core/bot_client.py::get_bot()). Тихий no-op, если пользователь ни
    разу не вызывал /day_tasks — это не баг, а нормальное "фичей не
    пользовались", как и у похожих необязательных уведомлений в
    проекте (см. record_task_completion в f_task_nag.py)."""
    ref = await _load_message_ref(user_id)
    if ref is None:
        return
    chat_id, message_id, pinned_date = ref
    if pinned_date is None:
        # Старый формат ссылки без даты (переходный период, см.
        # _load_message_ref) — разово бутстрапим на "сегодня" прямо
        # сейчас и сохраняем дальше уже с датой.
        pinned_date = await user_today(user_id)
        await _save_message_ref(user_id, chat_id, message_id, pinned_date)
    rich_message = await _render(user_id, pinned_date)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, rich_message=rich_message
        )
    except Exception:
        # Сообщение могли удалить руками, оно могло устареть и т.п. —
        # не должно ронять тот реальный вызов (создание/правку задачи),
        # из-за которого мы сюда попали. Забываем ссылку, чтобы не
        # пытаться её же на каждую следующую правку — следующий
        # /day_tasks заведёт новую.
        logger.info("Не удалось обновить /day_tasks сообщение (%s) — забываю ссылку", user_id)
        await _forget_message_ref(user_id)


async def advance_day_task_date(bot: Bot, user_id: int, today: date) -> None:
    """Вызывается утренней рассылкой (scheduler/jobs.py::_morning_digest,
    внутри той же проверки morning_digest_enabled) — и ТОЛЬКО ею:
    единственное место, где показанный день закреплённого сообщения
    сдвигается без явного действия пользователя (см. докстринг модуля).
    Тихий no-op, если /day_tasks ни разу не вызывали — тот же
    принцип, что refresh_day_task_message."""
    ref = await _load_message_ref(user_id)
    if ref is None:
        return
    chat_id, message_id, _ = ref
    rich_message = await _render(user_id, today)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, rich_message=rich_message
        )
        await _save_message_ref(user_id, chat_id, message_id, today)
    except Exception:
        logger.info(
            "Не удалось сдвинуть закреплённое /day_tasks на новый день (%s) — забываю ссылку",
            user_id,
        )
        await _forget_message_ref(user_id)


@router.message(Command("day_tasks"))
async def handle_set_day_task(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    user_id = message.from_user.id
    # Ручной вызов команды — явное "покажи мне СЕЙЧАС", всегда today,
    # даже если до этого показанный день был вчерашним (см. докстринг
    # модуля — единственное другое место, что двигает дату, это
    # advance_day_task_date из утренней рассылки).
    today = await user_today(user_id)
    rich_message = await _render(user_id, today)

    ref = await _load_message_ref(user_id)

    # Повторный вызов команды — правим уже существующее сообщение, а не
    # плодим новое; если его больше нет (удалено вручную, чат другой) —
    # тихо откатываемся на отправку нового. Уже закреплено с первого
    # раза — editMessageText статус pin не трогает, перезакреплять не
    # нужно. Подтверждение шлём только при первом включении (ниже) —
    # повторный вызов не должен спамить тем же текстом каждый раз.
    if ref is not None:
        chat_id, message_id, _ = ref
        try:
            await message.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, rich_message=rich_message
            )
            await _save_message_ref(user_id, chat_id, message_id, today)
            return
        except Exception:
            logger.info("Не удалось отредактировать старое сообщение /day_tasks — шлю новое")

    sent = await message.bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_message)
    await _save_message_ref(user_id, sent.chat.id, sent.message_id, today)
    try:
        await message.bot.pin_chat_message(
            chat_id=sent.chat.id, message_id=sent.message_id, disable_notification=True
        )
    except Exception:
        # Не должно ронять уже успешную отправку сообщения — просто
        # останется обычным, не закреплённым (например, нет прав на pin
        # в каком-то нестандартном чате).
        logger.info("Не удалось закрепить сообщение /day_tasks (%s)", user_id)

    # Явное подтверждение опт-ина (фидбек 2026-10-22) — раньше результатом
    # команды было ТОЛЬКО само rich-сообщение, без объяснения, что оно
    # теперь будет обновляться само каждое утро; это и создавало ощущение
    # "нажал — ничего не произошло".
    await message.answer(
        "Готово — закрепил. Каждое утро буду сам обновлять этот список на новый день, "
        "ничего нажимать для этого не нужно. Команда /day_tasks и дальше работает "
        "как мгновенный ресинк на сейчас, если понадобится."
    )


@router.callback_query(F.data.startswith("daytask_toggle:"))
async def handle_toggle_task(callback: CallbackQuery, storage: BaseStorage) -> None:
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
        now_done = task.done
        toggled_due_date = task.due_date.date() if task.due_date else None
        await session.commit()

    await invalidate_tasks_cache(user_id)

    # Перечитываем ВЕСЬ список заново (не только эту задачу) — заодно
    # подхватит любые изменения, случившиеся где-то ещё с прошлой
    # отрисовки. Дата — показанный день (pinned_date), НЕ user_today()
    # напрямую: тап по кнопке посреди ночи не должен молча перепрыгнуть
    # сообщение на уже наступивший календарный день (см. докстринг
    # модуля) — это право только у утренней рассылки.
    ref = await _load_message_ref(user_id)
    target_date = ref[2] if ref and ref[2] is not None else await user_today(user_id)
    rich_message = await _render(user_id, target_date)
    await callback.message.bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        rich_message=rich_message,
    )
    await callback.answer()

    if now_done:
        # Похвала при закрытии дня (фидбек 2026-10-24) — импорт внутри
        # функции: f_morning_advice.py сам импортирует
        # refresh_day_task_message ИЗ этого модуля, импорт на уровне
        # модуля в обе стороны дал бы цикл.
        from src.handlers.f_morning_advice import maybe_praise_closed_day

        try:
            await maybe_praise_closed_day(callback.bot, storage, user_id, toggled_due_date)
        except Exception:
            logger.exception("Не удалось проверить похвалу за закрытый день (%s)", user_id)
