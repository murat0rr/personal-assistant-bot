import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from src.core import ai_analytics
from src.core.auth import list_authorized_user_ids
from src.core.config import settings
from src.core.db import async_session
from src.core.goals import GOAL_TIER_BOUNDS
from src.core.google_calendar_sync import sync_user_calendar
from src.core.habits import list_habits
from src.core.recurring_tasks import materialize_due_rules
from src.core.task_templates import create_ai_template, list_templates
from src.core.user_location import user_schedule_hours, user_timezone, user_today
from src.handlers.f4_diary import DiaryStates, ask_question
from src.handlers.f9_finance import FINANCE_GUIDE
from src.handlers.f11_weekly_review import build_weekly_review
from src.handlers.f12_briefing import build_morning_briefing
from src.handlers.f_goals import start_goal_flow
from src.handlers.f_morning_advice import send_morning_advice
from src.handlers.f_reminders import check_reminders
from src.handlers.f_task_nag import check_and_nudge
from src.handlers.miniapp_tasks import build_task_board
from src.integrations.claude_client import suggest_new_templates, tidy_task_titles
from src.models.chat_message import ChatMessage
from src.models.screen_time import ScreenTime
from src.models.task import Task

logger = logging.getLogger(__name__)

# Три джобы ниже (screen_time_digest, finance_reminder, evening_diary)
# остаются только у владельца (Phase 40, см. их регистрацию в конце
# _job_specs) — не потому что "ещё не доделано", а потому что они
# завязаны на что-то физически единственное: конкретный телефон с
# MacroDroid (экранное время), конкретный банк/выписка (финансы),
# Notion-дневник одного воркспейса (см. TECHDEBT.md — то же ограничение,
# что у заметок/дневника в api.py::_NOT_READY_FOR_OTHERS).


async def _ai_analytics_refresh_job(bot: Bot, user_id: int) -> None:
    """Раз в сутки, до того как пользователь обычно открывает Mini App
    (Phase 48) — пересчитывает текстовую ИИ-аналитику и кладёт в кэш
    (см. core/ai_analytics.py). До этой фазы её на каждое открытие
    вкладки "Аналитика" заново дёргал сам эндпоинт — теперь он просто
    читает то, что здесь посчитано. Не отчитывается в чат (в отличие от
    большинства джоб) — это тихий фоновый пересчёт кэша, не то, что
    пользователю нужно видеть каждое утро."""
    logger.info("Обновляю кэш ИИ-аналитики (%s)", user_id)
    await ai_analytics.refresh_summary(user_id)


async def _materialize_recurring_tasks_job(bot: Bot, user_id: int) -> None:
    """До утренней сводки (08:00) — материализует сегодняшние occurrence
    повторяющихся задач как обычные Task-строки, ничего не создавая
    заранее (см. core/recurring_tasks.py). Дальше и утренняя сводка, и
    Mini App видят их как обычные задачи — специальной логики под них
    нигде больше не нужно."""
    logger.info("Материализую повторяющиеся задачи на сегодня (%s)", user_id)
    today = await user_today(user_id)
    created = await materialize_due_rules(user_id, today)
    if created:
        logger.info("Создано повторяющихся задач: %s", len(created))


async def _morning_digest(bot: Bot, storage: BaseStorage, user_id: int) -> None:
    logger.info("Формирую утреннюю сводку (%s)", user_id)
    today = await user_today(user_id)
    text = await build_morning_briefing(user_id, today)
    await bot.send_message(chat_id=user_id, text=text)
    # Совет по задачам на сегодня (Phase 23) — отдельным сообщением
    # следом, не смешивая с самой сводкой (у него своя интерактивная
    # клавиатура "Добавить"/"Не сегодня").
    try:
        await send_morning_advice(bot, storage, user_id, today)
    except Exception:
        logger.exception("Не удалось отправить совет по задачам на сегодня")


async def _reminders_job(bot: Bot, user_id: int) -> None:
    logger.info("Проверяю напоминания (%s)", user_id)
    today = await user_today(user_id)
    await check_reminders(bot, user_id, today)


async def _task_nag_sweep(bot: Bot, user_id: int) -> None:
    # Намёки о незакрытых задачах (Phase 59, команда /nag) — тонкий
    # wrapper, вся логика (включён ли, наступил ли порог X+N,
    # автоудаление через 59 минут) в check_and_nudge, тот же приём, что
    # у _reminders_job/check_reminders. Регистрируется отдельно от
    # остальных джобов ниже (IntervalTrigger, не CronTrigger) — см.
    # register_jobs_for_user.
    await check_and_nudge(bot, user_id)


async def _google_calendar_sync_job(bot: Bot, user_id: int) -> None:
    # Google Calendar (Phase 59-style — тонкий wrapper, вся логика в
    # sync_user_calendar) — тихо выходит, если аккаунт не подключён, так
    # что регистрируем безусловно для каждого пользователя, как
    # _task_nag_sweep, без предварительной проверки.
    await sync_user_calendar(bot, user_id)


async def _evening_diary(bot: Bot, storage: BaseStorage) -> None:
    # Только владелец (см. _OWNER_ONLY_JOB_NAMES) — дневник в Notion,
    # один воркспейс.
    logger.info("Запускаю вечерний опрос дневника")
    key = StorageKey(
        bot_id=bot.id,
        chat_id=settings.telegram_user_id,
        user_id=settings.telegram_user_id,
    )
    state = FSMContext(storage=storage, key=key)
    await state.set_data({})
    await ask_question(bot, state, DiaryStates.physical)


async def _tidy_inbox_job(bot: Bot, user_id: int) -> None:
    """Ночной разбор инбокса (Phase 22) — причёсывает заголовки задач в
    инбоксе (та же выборка, что build_task_board: без даты или
    просроченные невыполненные), не трогая смысл. Отчитывается только
    если что-то реально поменялось — тихая ночь без изменений не должна
    ничего слать."""
    logger.info("Разбираю инбокс (%s)", user_id)
    today = await user_today(user_id)

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.archived.is_(False), Task.user_id == user_id)
        )
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
            if task is None or task.user_id != user_id:
                continue
            task.title = new_title
            changes.append((old_title, new_title))
        if changes:
            await session.commit()

    if changes:
        lines = "\n".join(f"— «{old}» → «{new}»" for old, new in changes)
        await bot.send_message(
            chat_id=user_id,
            text=f"🧹 Причесал заголовки в инбоксе:\n{lines}",
        )


async def _cleanup_old_messages(bot: Bot, user_id: int) -> None:
    tz = await user_timezone(user_id)
    now = datetime.now(tz)
    today = now.date()
    # Telegram физически не даёт удалить сообщение старше 48 часов — после
    # этого порога дальнейшие попытки бессмысленны, строку можно забыть.
    # Строка удаляется из БД только если сообщение реально удалено (или
    # Telegram явно говорит, что удалять больше нечего) — иначе остаётся
    # и уйдёт в следующую попытку ночью (см. TECHDEBT-история этого фикса
    # в SPEC.md, Phase 38).
    give_up_after = now - timedelta(hours=47)

    deleted = 0
    async with async_session() as session:
        # chat_id, не только сам факт "сообщение существует" (Phase 40) —
        # message_id уникален только внутри одного чата, у разных
        # пользователей могут быть строки с одинаковым message_id (см.
        # models/chat_message.py).
        result = await session.execute(select(ChatMessage).where(ChatMessage.chat_id == user_id))
        candidates = [
            row for row in result.scalars().all() if row.sent_at.astimezone(tz).date() < today
        ]

        for row in candidates:
            try:
                await bot.delete_message(chat_id=user_id, message_id=row.message_id)
            except TelegramBadRequest:
                if row.sent_at >= give_up_after:
                    continue
            await session.delete(row)
            deleted += 1

        await session.commit()

    logger.info(
        "Автоочистка чата (%s): удалено %s из %s сообщений", user_id, deleted, len(candidates)
    )


async def _finance_reminder_job(bot: Bot) -> None:
    # Только владелец (см. _OWNER_ONLY_JOB_NAMES) — инструкция специфична
    # для его собственного банка.
    logger.info("Напоминаю про выписку за месяц")
    await bot.send_message(chat_id=settings.telegram_user_id, text=FINANCE_GUIDE)


async def _screen_time_digest(bot: Bot) -> None:
    # Только владелец (см. _OWNER_ONLY_JOB_NAMES) — экранное время
    # приходит с одного конкретного телефона через MacroDroid.
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


async def _weekly_review(bot: Bot, user_id: int) -> None:
    logger.info("Собираю итоги недели (%s)", user_id)
    today = await user_today(user_id)
    text = await build_weekly_review(user_id, today)
    await bot.send_message(chat_id=user_id, text=text)


async def _habit_reminders(bot: Bot, user_id: int) -> None:
    logger.info("Проверяю несделанные привычки (%s)", user_id)
    today = await user_today(user_id)
    habits = await list_habits(user_id)
    missed = [h for h in habits if h["target_frequency"] == "daily" and h["last_checked"] != today]
    if not missed:
        return
    names = "\n".join(f"— {h['name']}" for h in missed)
    await bot.send_message(
        chat_id=user_id,
        text=f"⏰ Не забудь отметить привычки за сегодня:\n{names}",
    )


async def _goal_prompt_job(bot: Bot, storage: BaseStorage, user_id: int, tier: str) -> None:
    logger.info("Запускаю опрос целей: %s (%s)", tier, user_id)
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    state = FSMContext(storage=storage, key=key)
    today = await user_today(user_id)
    bounds = GOAL_TIER_BOUNDS[tier](today)
    await start_goal_flow(bot, state, user_id, tier, *bounds)


async def _suggest_templates_job(bot: Bot, user_id: int) -> None:
    """Раз в неделю (воскресенье, 09:00) — смотрит на заголовки задач за
    последние 7 дней и предлагает новые шаблоны частых задач через Claude
    (см. claude_client.suggest_new_templates). Не чаще 1 раза в неделю —
    ровно как попросили."""
    logger.info("Анализирую частые задачи для новых шаблонов (%s)", user_id)
    tz = await user_timezone(user_id)
    # due_date в БД — naive timestamp (локальное время без tz), см.
    # models/task.py — сравнение тоже должно быть naive, иначе asyncpg
    # ругается на offset-aware datetime для timestamp without time zone.
    since = (datetime.now(tz) - timedelta(days=7)).replace(tzinfo=None)

    async with async_session() as session:
        result = await session.execute(
            select(Task.title).where(Task.due_date >= since, Task.user_id == user_id)
        )
        recent_titles = [row[0] for row in result.all()]

    existing = await list_templates(user_id, datetime.now(tz).date())
    existing_titles = [t["title"] for t in existing]

    suggestions = await suggest_new_templates(recent_titles, existing_titles)
    if not suggestions:
        logger.info("Новых шаблонов не предложено")
        return

    for title in suggestions:
        await create_ai_template(user_id, title)

    names = "\n".join(f"— {title}" for title in suggestions)
    await bot.send_message(
        chat_id=user_id,
        text=f"✨ Добавил новые шаблоны частых задач по итогам недели:\n{names}",
    )


def _job_specs(
    bot: Bot,
    storage: BaseStorage,
    user_id: int,
    tz_name: str,
    morning_hour: int,
    evening_hour: int,
) -> list[tuple[str, Any, dict, list]]:
    """Единый источник правды для расписания джобов ОДНОГО пользователя
    (Phase 40 — раньше был один глобальный набор джобов на всё
    приложение, теперь у каждого авторизованного свой, в своём часовом
    поясе). id каждого джоба включает user_id — раньше на одно имя джобы
    приходился один-единственный экземпляр, теперь их по одному на
    пользователя, id должны быть уникальны в рамках всего scheduler.
    Используется и register_jobs_for_user (первичная регистрация), и
    reschedule_user_jobs (Phase 39/40/61 — команды /timezone, /morning,
    /evening: пересобирают триггеры ЭТОГО пользователя в рантайме).
    morning_hour/evening_hour — уже разрешённые значения (дефолт
    подставлен вызывающей стороной, см. user_location.py::
    user_schedule_hours), не сырые nullable-поля из БД."""
    is_owner = user_id == settings.telegram_user_id
    specs: list[tuple[str, Any, dict, list]] = [
        (
            "morning_digest",
            _morning_digest,
            {"hour": morning_hour, "minute": 0},
            [bot, storage, user_id],
        ),
        ("reminders", _reminders_job, {"hour": 8, "minute": 0}, [bot, user_id]),
        (
            "weekly_review",
            _weekly_review,
            {"day_of_week": "sun", "hour": 19, "minute": 0},
            [bot, user_id],
        ),
        ("habit_reminders", _habit_reminders, {"hour": 20, "minute": 0}, [bot, user_id]),
        ("cleanup_old_messages", _cleanup_old_messages, {"hour": 0, "minute": 5}, [bot, user_id]),
        # Материализация повторяющихся задач (Phase 21) — до утренней сводки.
        (
            "materialize_recurring_tasks",
            _materialize_recurring_tasks_job,
            {"hour": 7, "minute": 0},
            [bot, user_id],
        ),
        # Кэш ИИ-аналитики (Phase 48) — до materialize_recurring_tasks
        # (07:00) и morning_digest (08:00), чтобы к моменту, как
        # пользователь обычно открывает Mini App утром, кэш уже был свежим.
        (
            "ai_analytics_refresh",
            _ai_analytics_refresh_job,
            {"hour": 6, "minute": 30},
            [bot, user_id],
        ),
        # Разбор инбокса (Phase 22) — ночью, до материализации повторяющихся
        # (07:00) и утренней сводки (08:00), не пересекается с ними.
        ("tidy_inbox", _tidy_inbox_job, {"hour": 3, "minute": 0}, [bot, user_id]),
        (
            "suggest_templates",
            _suggest_templates_job,
            {"day_of_week": "sun", "hour": 9, "minute": 0},
            [bot, user_id],
        ),
        # Цели (Phase 20) — недельные каждое воскресенье; месячные в начале
        # месяца; годовые — только в январе. Раздельные дни (2/4 числа),
        # чтобы не наваливать несколько опросов в одно утро.
        (
            "goal_prompt_weekly",
            _goal_prompt_job,
            {"day_of_week": "sun", "hour": 12, "minute": 0},
            [bot, storage, user_id, "weekly"],
        ),
        (
            "goal_prompt_monthly",
            _goal_prompt_job,
            {"day": 2, "hour": 10, "minute": 0},
            [bot, storage, user_id, "monthly"],
        ),
        (
            "goal_prompt_yearly",
            _goal_prompt_job,
            {"day": 4, "hour": 10, "minute": 0, "month": 1},
            [bot, storage, user_id, "yearly"],
        ),
    ]
    if is_owner:
        specs += [
            ("screen_time_digest", _screen_time_digest, {"hour": 8, "minute": 0}, [bot]),
            (
                "finance_reminder",
                _finance_reminder_job,
                {"day": 1, "hour": 8, "minute": 0},
                [bot],
            ),
            (
                "evening_diary",
                _evening_diary,
                {"hour": evening_hour, "minute": 0},
                [bot, storage],
            ),
        ]
    return [
        (f"{name}:{user_id}", func, {**trigger, "timezone": tz_name}, args)
        for name, func, trigger, args in specs
    ]


async def register_jobs_for_user(
    scheduler: AsyncIOScheduler, bot: Bot, storage: BaseStorage, user_id: int
) -> None:
    """Регистрирует (или полностью пересобирает — replace_existing) весь
    личный набор джобов одного пользователя. Вызывается на старте для
    каждого уже авторизованного (см. setup_scheduler) и сразу при
    успешной авторизации нового пользователя (см. handlers/f_auth.py)."""
    tz_name = str(await user_timezone(user_id))
    morning_hour, evening_hour = await user_schedule_hours(user_id)
    for job_id, func, trigger_kwargs, args in _job_specs(
        bot, storage, user_id, tz_name, morning_hour, evening_hour
    ):
        scheduler.add_job(
            func, CronTrigger(**trigger_kwargs), args=args, id=job_id, replace_existing=True
        )
    # Намёки о незакрытых задачах (Phase 59) — единственный периодический
    # (не cron) джоб в проекте, регистрируется отдельно от _job_specs
    # (тот контракт жёстко завязан на CronTrigger). Опрос раз в 15 минут
    # — разрешение проверки, сам намёк придёт не позже, чем через 15
    # минут после расчётного порога, не секунда в секунду. Часовой пояс
    # IntervalTrigger не важен — reschedule_user_jobs его не трогает.
    scheduler.add_job(
        _task_nag_sweep,
        IntervalTrigger(minutes=15),
        args=[bot, user_id],
        id=f"task_nag_sweep:{user_id}",
        replace_existing=True,
    )
    # Google Calendar (Phase 64) — тот же приём, что task_nag_sweep выше:
    # единственный, кто физически привязан к внешнему опросу, не к
    # тихому часу/расписанию дня, поэтому IntervalTrigger, не CronTrigger
    # из _job_specs. Доступно любому пользователю (не только владельцу,
    # см. _job_specs выше) — у каждого свой Google-аккаунт, это не
    # физически единственный ресурс вроде экранного времени.
    scheduler.add_job(
        _google_calendar_sync_job,
        IntervalTrigger(minutes=20),
        args=[bot, user_id],
        id=f"google_calendar_sync:{user_id}",
        replace_existing=True,
    )


def unregister_jobs_for_user(scheduler: AsyncIOScheduler, user_id: int) -> None:
    """Снимает все личные джобы пользователя — на будущее (если появится
    возможность отозвать доступ), сейчас ничего не вызывает эту функцию."""
    suffix = f":{user_id}"
    for job in scheduler.get_jobs():
        if job.id.endswith(suffix):
            scheduler.remove_job(job.id)


async def setup_scheduler(bot: Bot, storage: BaseStorage) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    for user_id in await list_authorized_user_ids():
        await register_jobs_for_user(scheduler, bot, storage, user_id)
    return scheduler


async def reschedule_user_jobs(
    scheduler: AsyncIOScheduler, bot: Bot, storage: BaseStorage, user_id: int
) -> None:
    """Что-то в личном расписании пользователя сменилось в рантайме —
    часовой пояс (/timezone, handlers/f_timezone.py), час утренней
    рассылки или вечерней рефлексии (/morning /evening, Phase 61,
    handlers/f_schedule.py) — пересобирает триггеры ЕГО ЛИЧНЫХ джобов
    (не всех пользователей — у каждого своё). Читает актуальные
    значения из БД сама (не принимает параметром, как было раньше
    только с tz_name) — один пересборщик на все три случая, вызывающей
    стороне достаточно один раз сохранить своё поле и позвать эту
    функцию. CronTrigger резолвит tzinfo/час один раз при создании (не
    держит живую ссылку на scheduler.timezone), так что нужно явно
    пересоздать каждый триггер, не просто поменять атрибут задним
    числом."""
    tz_name = str(await user_timezone(user_id))
    morning_hour, evening_hour = await user_schedule_hours(user_id)
    for job_id, func, trigger_kwargs, args in _job_specs(
        bot, storage, user_id, tz_name, morning_hour, evening_hour
    ):
        if scheduler.get_job(job_id) is not None:
            scheduler.reschedule_job(job_id, trigger=CronTrigger(**trigger_kwargs))
        else:
            scheduler.add_job(func, CronTrigger(**trigger_kwargs), args=args, id=job_id)
