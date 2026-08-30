import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session
from src.core.goals import GOAL_TIER_BOUNDS
from src.core.habits import list_habits
from src.core.recurring_tasks import materialize_due_rules
from src.core.task_templates import create_ai_template, list_templates
from src.handlers.f4_diary import DiaryStates, ask_question
from src.handlers.f9_finance import FINANCE_GUIDE
from src.handlers.f11_weekly_review import build_weekly_review
from src.handlers.f12_briefing import build_morning_briefing
from src.handlers.f_goals import start_goal_flow
from src.handlers.f_morning_advice import send_morning_advice
from src.handlers.f_reminders import check_reminders
from src.handlers.miniapp_tasks import build_task_board
from src.integrations.claude_client import suggest_new_templates, tidy_task_titles
from src.models.chat_message import ChatMessage
from src.models.screen_time import ScreenTime
from src.models.task import Task

logger = logging.getLogger(__name__)


async def _materialize_recurring_tasks_job(bot: Bot) -> None:
    """До утренней сводки (08:00) — материализует сегодняшние occurrence
    повторяющихся задач как обычные Task-строки, ничего не создавая
    заранее (см. core/recurring_tasks.py). Дальше и утренняя сводка, и
    Mini App видят их как обычные задачи — специальной логики под них
    нигде больше не нужно."""
    logger.info("Материализую повторяющиеся задачи на сегодня")
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    created = await materialize_due_rules(today)
    if created:
        logger.info("Создано повторяющихся задач: %s", len(created))


async def _morning_digest(bot: Bot, storage: BaseStorage) -> None:
    logger.info("Формирую утреннюю сводку")
    text = await build_morning_briefing()
    await bot.send_message(chat_id=settings.telegram_user_id, text=text)
    # Совет по задачам на сегодня (Phase 23) — отдельным сообщением
    # следом, не смешивая с самой сводкой (у него своя интерактивная
    # клавиатура "Добавить"/"Не сегодня").
    try:
        await send_morning_advice(bot, storage)
    except Exception:
        logger.exception("Не удалось отправить совет по задачам на сегодня")


async def _reminders_job(bot: Bot) -> None:
    logger.info("Проверяю напоминания")
    await check_reminders(bot)


async def _evening_diary(bot: Bot, storage: BaseStorage) -> None:
    logger.info("Запускаю вечерний опрос дневника")
    key = StorageKey(
        bot_id=bot.id,
        chat_id=settings.telegram_user_id,
        user_id=settings.telegram_user_id,
    )
    state = FSMContext(storage=storage, key=key)
    await state.set_data({})
    await ask_question(bot, state, DiaryStates.physical)


async def _tidy_inbox_job(bot: Bot) -> None:
    """Ночной разбор инбокса (Phase 22) — причёсывает заголовки задач в
    инбоксе (та же выборка, что build_task_board: без даты или
    просроченные невыполненные), не трогая смысл. Отчитывается только
    если что-то реально поменялось — тихая ночь без изменений не должна
    ничего слать."""
    logger.info("Разбираю инбокс")
    today = datetime.now(ZoneInfo(settings.timezone)).date()

    async with async_session() as session:
        result = await session.execute(select(Task).where(Task.archived.is_(False)))
        tasks = result.scalars().all()
    board = build_task_board(list(tasks), today)
    inbox_tasks = {t["id"]: t for t in board["inbox"]}
    if not inbox_tasks:
        return

    ids = list(inbox_tasks.keys())
    titles = [inbox_tasks[i]["title"] for i in ids]
    tidied = await tidy_task_titles(titles)

    changes: list[tuple[str, str]] = []
    async with async_session() as session:
        for item in tidied:
            if not item.changed or not (0 <= item.index < len(ids)):
                continue
            new_title = item.tidied_title.strip()
            old_title = titles[item.index]
            if not new_title or new_title == old_title:
                continue
            task = await session.get(Task, ids[item.index])
            if task is None:
                continue
            task.title = new_title
            changes.append((old_title, new_title))
        if changes:
            await session.commit()

    if changes:
        lines = "\n".join(f"— «{old}» → «{new}»" for old, new in changes)
        await bot.send_message(
            chat_id=settings.telegram_user_id,
            text=f"🧹 Причесал заголовки в инбоксе:\n{lines}",
        )


async def _cleanup_old_messages(bot: Bot) -> None:
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    today = now.date()
    # Telegram физически не даёт удалить сообщение старше 48 часов — после
    # этого порога дальнейшие попытки бессмысленны, строку можно забыть.
    # До порога — БАГ (найден при разборе жалобы "очистка не работает"):
    # строка удалялась из chat_messages независимо от того, удалилось ли
    # само сообщение в Telegram. Любая временная ошибка (сеть, недоступен
    # API и т.п.) на bot.delete_message молча "забывала" сообщение
    # навсегда — повторной попытки на следующий день уже не было, а лог
    # всё равно бодро отчитывался «удалено N», хотя на самом деле не
    # удалялось ничего. Теперь строка удаляется из БД только если
    # сообщение реально удалено (или Telegram явно говорит, что удалять
    # больше нечего) — иначе остаётся и уйдёт в следующую попытку ночью.
    give_up_after = now - timedelta(hours=47)

    deleted = 0
    async with async_session() as session:
        result = await session.execute(select(ChatMessage))
        candidates = [
            row for row in result.scalars().all() if row.sent_at.astimezone(tz).date() < today
        ]

        for row in candidates:
            try:
                await bot.delete_message(
                    chat_id=settings.telegram_user_id, message_id=row.message_id
                )
            except TelegramBadRequest:
                # Уже удалено вручную, чат недоступен и т.п. — Telegram
                # прямо сказал "нечего удалять" или "нельзя". Если ещё не
                # уткнулись в 48-часовой порог — оставляем строку на
                # повторную попытку следующей ночью (мало ли API
                # подглючило именно сейчас); иначе дальше пытаться нет
                # смысла — забываем.
                if row.sent_at >= give_up_after:
                    continue
            await session.delete(row)
            deleted += 1

        await session.commit()

    logger.info("Автоочистка чата: удалено %s из %s сообщений", deleted, len(candidates))


async def _finance_reminder_job(bot: Bot) -> None:
    logger.info("Напоминаю про выписку за месяц")
    await bot.send_message(chat_id=settings.telegram_user_id, text=FINANCE_GUIDE)


async def _screen_time_digest(bot: Bot) -> None:
    tz = ZoneInfo(settings.timezone)
    yesterday = (datetime.now(tz) - timedelta(days=1)).date()

    async with async_session() as session:
        entry = await session.get(ScreenTime, yesterday)

    if entry is None:
        logger.info("Экранное время за %s не пришло — пропускаю сводку", yesterday)
        return

    hours, minutes = divmod(entry.total_minutes, 60)
    await bot.send_message(
        chat_id=settings.telegram_user_id,
        text=f"📱 Экранное время вчера: {hours}ч {minutes}м",
    )


async def _weekly_review(bot: Bot) -> None:
    logger.info("Собираю итоги недели")
    text = await build_weekly_review()
    await bot.send_message(chat_id=settings.telegram_user_id, text=text)


async def _habit_reminders(bot: Bot) -> None:
    logger.info("Проверяю несделанные привычки")
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    habits = await list_habits()
    missed = [h for h in habits if h["target_frequency"] == "daily" and h["last_checked"] != today]
    if not missed:
        return
    names = "\n".join(f"— {h['name']}" for h in missed)
    await bot.send_message(
        chat_id=settings.telegram_user_id,
        text=f"⏰ Не забудь отметить привычки за сегодня:\n{names}",
    )


async def _goal_prompt_job(bot: Bot, storage: BaseStorage, tier: str) -> None:
    logger.info("Запускаю опрос целей: %s", tier)
    key = StorageKey(
        bot_id=bot.id,
        chat_id=settings.telegram_user_id,
        user_id=settings.telegram_user_id,
    )
    state = FSMContext(storage=storage, key=key)
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    bounds = GOAL_TIER_BOUNDS[tier](today)
    await start_goal_flow(bot, state, tier, *bounds)


async def _suggest_templates_job(bot: Bot) -> None:
    """Раз в неделю (воскресенье, 09:00) — смотрит на заголовки задач за
    последние 7 дней и предлагает новые шаблоны частых задач через Claude
    (см. claude_client.suggest_new_templates). Не чаще 1 раза в неделю —
    ровно как попросили."""
    logger.info("Анализирую частые задачи для новых шаблонов")
    tz = ZoneInfo(settings.timezone)
    # due_date в БД — naive timestamp (локальное время без tz), см.
    # models/task.py — сравнение тоже должно быть naive, иначе asyncpg
    # ругается на offset-aware datetime для timestamp without time zone.
    since = (datetime.now(tz) - timedelta(days=7)).replace(tzinfo=None)

    async with async_session() as session:
        result = await session.execute(select(Task.title).where(Task.due_date >= since))
        recent_titles = [row[0] for row in result.all()]

    existing = await list_templates(datetime.now(tz).date())
    existing_titles = [t["title"] for t in existing]

    suggestions = await suggest_new_templates(recent_titles, existing_titles)
    if not suggestions:
        logger.info("Новых шаблонов не предложено")
        return

    for title in suggestions:
        await create_ai_template(title)

    names = "\n".join(f"— {title}" for title in suggestions)
    await bot.send_message(
        chat_id=settings.telegram_user_id,
        text=f"✨ Добавил новые шаблоны частых задач по итогам недели:\n{names}",
    )


def setup_scheduler(bot: Bot, storage: BaseStorage) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(_morning_digest, CronTrigger(hour=8, minute=0), args=[bot, storage])
    scheduler.add_job(_reminders_job, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_screen_time_digest, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_finance_reminder_job, CronTrigger(day=1, hour=8, minute=0), args=[bot])
    scheduler.add_job(_weekly_review, CronTrigger(day_of_week="sun", hour=19, minute=0), args=[bot])
    scheduler.add_job(_habit_reminders, CronTrigger(hour=20, minute=0), args=[bot])
    scheduler.add_job(_evening_diary, CronTrigger(hour=21, minute=0), args=[bot, storage])
    scheduler.add_job(_cleanup_old_messages, CronTrigger(hour=0, minute=5), args=[bot])
    # Материализация повторяющихся задач (Phase 21) — до утренней сводки.
    scheduler.add_job(_materialize_recurring_tasks_job, CronTrigger(hour=7, minute=0), args=[bot])
    # Разбор инбокса (Phase 22) — ночью, до материализации повторяющихся
    # (07:00) и утренней сводки (08:00), не пересекается с ними.
    scheduler.add_job(_tidy_inbox_job, CronTrigger(hour=3, minute=0), args=[bot])
    scheduler.add_job(
        _suggest_templates_job, CronTrigger(day_of_week="sun", hour=9, minute=0), args=[bot]
    )
    # Цели (Phase 20) — недельные каждое воскресенье; месячные в начале
    # месяца; годовые — только в январе. Раздельные дни (2/4 числа),
    # чтобы не наваливать несколько опросов в одно утро.
    scheduler.add_job(
        _goal_prompt_job,
        CronTrigger(day_of_week="sun", hour=12, minute=0),
        args=[bot, storage, "weekly"],
    )
    scheduler.add_job(
        _goal_prompt_job, CronTrigger(day=2, hour=10, minute=0), args=[bot, storage, "monthly"]
    )
    scheduler.add_job(
        _goal_prompt_job,
        CronTrigger(day=4, hour=10, minute=0, month=1),
        args=[bot, storage, "yearly"],
    )
    return scheduler
