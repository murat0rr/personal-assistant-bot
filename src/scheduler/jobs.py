import logging
from datetime import date, datetime, timedelta
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
from src.core.habits import list_habits
from src.core.recurring_tasks import materialize_due_rules
from src.core.task_templates import create_ai_template, list_templates
from src.handlers.f4_diary import DiaryStates, ask_question
from src.handlers.f9_finance import FINANCE_GUIDE
from src.handlers.f11_weekly_review import build_weekly_review
from src.handlers.f12_briefing import build_morning_briefing
from src.handlers.f_goals import start_goal_flow
from src.handlers.f_reminders import check_reminders
from src.integrations.claude_client import suggest_new_templates
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


async def _morning_digest(bot: Bot) -> None:
    logger.info("Формирую утреннюю сводку")
    text = await build_morning_briefing()
    await bot.send_message(chat_id=settings.telegram_user_id, text=text)


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


async def _cleanup_old_messages(bot: Bot) -> None:
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()

    async with async_session() as session:
        result = await session.execute(select(ChatMessage))
        old_messages = [
            row for row in result.scalars().all() if row.sent_at.astimezone(tz).date() < today
        ]

        for row in old_messages:
            try:
                await bot.delete_message(
                    chat_id=settings.telegram_user_id, message_id=row.message_id
                )
            except TelegramBadRequest:
                # уже удалено вручную, старше 48ч и т.п. — не критично
                pass
            await session.delete(row)

        await session.commit()

    logger.info("Автоочистка чата: удалено сообщений %s", len(old_messages))


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


def _week_bounds(today: date) -> tuple[date, date]:
    # Цели на "предстоящую неделю" — джоба стреляет в воскресенье, значит
    # следующий понедельник всегда tomorrow (today.weekday()==6).
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return monday, monday + timedelta(days=6)


def _month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    next_month = start.replace(day=28) + timedelta(days=4)
    end = next_month.replace(day=1) - timedelta(days=1)
    return start, end


def _quarter_bounds(today: date) -> tuple[date, date]:
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    start = today.replace(month=quarter_start_month, day=1)
    end_month = quarter_start_month + 2
    next_month = start.replace(month=end_month, day=28) + timedelta(days=4)
    end = next_month.replace(day=1) - timedelta(days=1)
    return start, end


def _year_bounds(today: date) -> tuple[date, date]:
    return today.replace(month=1, day=1), today.replace(month=12, day=31)


async def _goal_prompt_job(bot: Bot, storage: BaseStorage, tier: str) -> None:
    logger.info("Запускаю опрос целей: %s", tier)
    key = StorageKey(
        bot_id=bot.id,
        chat_id=settings.telegram_user_id,
        user_id=settings.telegram_user_id,
    )
    state = FSMContext(storage=storage, key=key)
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    bounds = {
        "weekly": _week_bounds,
        "monthly": _month_bounds,
        "quarterly": _quarter_bounds,
        "yearly": _year_bounds,
    }[tier](today)
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
    scheduler.add_job(_morning_digest, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_reminders_job, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_screen_time_digest, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(_finance_reminder_job, CronTrigger(day=1, hour=8, minute=0), args=[bot])
    scheduler.add_job(_weekly_review, CronTrigger(day_of_week="sun", hour=19, minute=0), args=[bot])
    scheduler.add_job(_habit_reminders, CronTrigger(hour=20, minute=0), args=[bot])
    scheduler.add_job(_evening_diary, CronTrigger(hour=21, minute=0), args=[bot, storage])
    scheduler.add_job(_cleanup_old_messages, CronTrigger(hour=0, minute=5), args=[bot])
    # Материализация повторяющихся задач (Phase 21) — до утренней сводки.
    scheduler.add_job(_materialize_recurring_tasks_job, CronTrigger(hour=7, minute=0), args=[bot])
    scheduler.add_job(
        _suggest_templates_job, CronTrigger(day_of_week="sun", hour=9, minute=0), args=[bot]
    )
    # Цели (Phase 20) — недельные каждое воскресенье; месячные в начале
    # месяца; квартальные/годовые — только в месяцы начала квартала/года.
    # Раздельные дни (2/3/4 числа), чтобы не наваливать несколько
    # опросов в одно утро.
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
        CronTrigger(day=3, hour=10, minute=0, month="1,4,7,10"),
        args=[bot, storage, "quarterly"],
    )
    scheduler.add_job(
        _goal_prompt_job,
        CronTrigger(day=4, hour=10, minute=0, month=1),
        args=[bot, storage, "yearly"],
    )
    return scheduler
