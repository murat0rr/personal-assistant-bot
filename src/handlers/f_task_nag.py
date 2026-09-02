import logging
import random
from datetime import datetime, timedelta, tzinfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from src.core.auth import is_authorized
from src.core.db import async_session
from src.core.user_location import user_timezone
from src.models.task import Task
from src.models.task_nag import TaskNagSettings

logger = logging.getLogger(__name__)

router = Router()

# Автоудаление намёка (требование пользователя) — 59, не 60, минут:
# запас в минуту на время между "пора удалять" и фактическим тиком
# джобы (интервал опроса ниже), Telegram всё равно не пускает точнее.
_NUDGE_DELETE_AFTER = timedelta(minutes=59)

# Тихие часы (Phase 60) — не слать намёки с полуночи до 7 утра, в
# часовом поясе пользователя (МСК по умолчанию, если свой пояс не
# задан — тот же дефолт, что и у user_timezone() везде в приложении,
# ничего отдельно не настраиваем). Автоудаление уже отправленного
# намёка эти часы не затрагивают — оно должно отработать всегда.
_QUIET_HOUR_START = 0
_QUIET_HOUR_END = 7  # не включительно — 7:00 уже можно

# Утренняя рассылка (Phase 60) — не намекать ближайший час после нее,
# человек и так только что получил дайджест. Час рассылки — константа
# 8 (текущее фиксированное время, см. scheduler/jobs.py::_job_specs);
# Phase 61 сделает его настраиваемым за пользователя (AuthorizedUser.
# morning_hour) — тогда сюда придёт то же значение параметром, не
# менять сам механизм. Длина окна (1 час) — разумный дефолт, конкретное
# число не называлось.
_MORNING_DIGEST_HOUR = 8
_MORNING_DIGEST_GRACE = timedelta(hours=1)

_HOURS_CHOICES = range(1, 7)  # 1..6, как попросили

# Неформальный тон, как просили ("эй бро тормозишь") — несколько
# вариантов, не одна и та же строка на каждый намёк подряд. Легко
# сократить до одной фиксированной фразы, если так лучше.
_PHRASES = [
    "Эй, бро, тормозишь.",
    "Ты там как, живой? Задачи сами себя не закроют.",
    "Ку-ку, напоминаю о твоём списке дел.",
]


async def _load(user_id: int) -> TaskNagSettings | None:
    async with async_session() as session:
        return await session.get(TaskNagSettings, user_id)


@router.message(Command("nag"))
async def toggle_nag(message: Message) -> None:
    if not message.from_user or not await is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return
    user_id = message.from_user.id

    async with async_session() as session:
        row = await session.get(TaskNagSettings, user_id)
        currently_enabled = row is not None and row.enabled
        if row is not None and currently_enabled:
            # Выключаем сразу, без переспроса — "такая же команда с
            # удалением напоминаний" (повторный /nag, пока включено,
            # это и есть выключение).
            row.enabled = False
            await session.commit()

    if currently_enabled:
        await message.answer("Намёки о задачах выключены.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(h), callback_data=f"nag_hours:{h}")
                for h in _HOURS_CHOICES
            ]
        ]
    )
    await message.answer(
        "Через сколько часов бездействия слать намёки о незакрытых задачах?",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("nag_hours:"))
async def set_nag_hours(callback: CallbackQuery) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if not callback.data:
        return

    hours = int(callback.data.split(":")[1])
    if hours not in _HOURS_CHOICES:
        await callback.answer()
        return

    user_id = callback.from_user.id
    now = datetime.now(await user_timezone(user_id))
    async with async_session() as session:
        existing = await session.get(TaskNagSettings, user_id)
        if existing is not None:
            existing.enabled = True
            existing.interval_hours = hours
            existing.streak_count = 0
            existing.last_event_at = now
            existing.last_nudge_message_id = None
            existing.last_nudge_sent_at = None
        else:
            session.add(
                TaskNagSettings(
                    user_id=user_id,
                    enabled=True,
                    interval_hours=hours,
                    streak_count=0,
                    last_event_at=now,
                )
            )
        await session.commit()

    await callback.answer("Намёки включены")
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Намёки о задачах включены.")


async def record_task_completion(user_id: int) -> None:
    """Любое выполнение задачи обнуляет счётчик намёков и сдвигает
    точку отсчёта — вызывается из api.py::mark_task_done. No-op, если
    строки ещё нет (фичей никогда не пользовались) — дешёвая проверка,
    не создаём строку впустую."""
    async with async_session() as session:
        row = await session.get(TaskNagSettings, user_id)
        if row is None:
            return
        row.streak_count = 0
        row.last_event_at = datetime.now(await user_timezone(user_id))
        await session.commit()


async def _has_pending_tasks(user_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Task.id)
            .where(Task.user_id == user_id, Task.done.is_(False), Task.archived.is_(False))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


def _aware(dt: datetime, tz: tzinfo) -> datetime:
    # last_event_at/last_nudge_sent_at читаются из БД — если колонка
    # почему-то вернулась naive (не должно, DateTime(timezone=True), но
    # дешёво подстраховаться тем же приёмом, что уже есть в проекте для
    # похожих сравнений), сравнение с aware `now` иначе упадёт с
    # TypeError вместо спокойного bool.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=tz)


def _should_delete_nudge(now: datetime, last_nudge_sent_at: datetime | None) -> bool:
    """Чистая функция для теста — не то же, что "включено": намёк
    удаляется по своему таймеру независимо от enabled/streak_count."""
    return last_nudge_sent_at is not None and now - last_nudge_sent_at >= _NUDGE_DELETE_AFTER


def _should_send_nudge(
    now: datetime, last_event_at: datetime, interval_hours: int, streak_count: int
) -> bool:
    """Чистая функция для теста — формула X+N (см. models/task_nag.py)."""
    wait = timedelta(hours=interval_hours + streak_count)
    return now - last_event_at >= wait


def _is_quiet_hour(now: datetime) -> bool:
    """Чистая функция для теста — тихие часы 00:00–07:00 (Phase 60)."""
    return _QUIET_HOUR_START <= now.hour < _QUIET_HOUR_END


def _within_morning_digest_grace(now: datetime, morning_hour: int = _MORNING_DIGEST_HOUR) -> bool:
    """Чистая функция для теста — окно тишины сразу после утренней
    рассылки (Phase 60). morning_hour — параметр, не жёсткая
    зависимость от константы, ради Phase 61 (настраиваемое время
    рассылки за пользователя)."""
    digest_at = now.replace(hour=morning_hour, minute=0, second=0, microsecond=0)
    return digest_at <= now < digest_at + _MORNING_DIGEST_GRACE


async def check_and_nudge(bot: Bot, user_id: int) -> None:
    """Периодическая проверка (см. scheduler/jobs.py::_task_nag_sweep,
    вызывается каждые 15 минут для каждого пользователя). Две
    независимые заботы в одном проходе: удалить просроченный намёк и
    решить, не пора ли прислать новый. Решающие условия вынесены в
    _should_delete_nudge/_should_send_nudge — чистые функции, покрыты
    тестами напрямую (этот async-обвес с БД/Bot — только живой прогон,
    см. SPEC.md Phase 59)."""
    row = await _load(user_id)
    if row is None:
        return

    tz = await user_timezone(user_id)
    now = datetime.now(tz)

    # Автоудаление — независимо от enabled: выключили фичу, но
    # последний намёк всё равно должен исчезнуть по своему таймеру.
    if row.last_nudge_message_id is not None:
        sent_at = row.last_nudge_sent_at
        if sent_at is not None and _should_delete_nudge(now, _aware(sent_at, tz)):
            try:
                await bot.delete_message(chat_id=user_id, message_id=row.last_nudge_message_id)
            except Exception:
                # Сообщение могло быть уже удалено пользователем вручную
                # или Telegram больше не даёт его удалить — не критично.
                logger.info(
                    "Не удалось удалить намёк %s (чат %s) — уже удалён?",
                    row.last_nudge_message_id,
                    user_id,
                )
            async with async_session() as session:
                db_row = await session.get(TaskNagSettings, user_id)
                if db_row is not None:
                    db_row.last_nudge_message_id = None
                    db_row.last_nudge_sent_at = None
                    await session.commit()

    if not row.enabled or row.interval_hours is None or row.last_event_at is None:
        return

    if not _should_send_nudge(
        now, _aware(row.last_event_at, tz), row.interval_hours, row.streak_count
    ):
        return

    # Тихие часы/окно после утренней рассылки (Phase 60) — таймер/
    # счётчик НЕ трогаем, тот же принцип, что и у "нет незакрытых
    # задач" ниже: как только окно кончится, следующая же проверка
    # (порог уже пройден) пришлёт намёк сразу же, не будет ждать заново
    # полный интервал.
    if _is_quiet_hour(now) or _within_morning_digest_grace(now):
        return

    # Незакрытых задач физически нет — намекать не о чем. Таймер/счётчик
    # НЕ трогаем: как только появится хоть одна незакрытая задача,
    # следующая же проверка (порог уже пройден) пришлёт намёк сразу.
    if not await _has_pending_tasks(user_id):
        return

    sent = await bot.send_message(chat_id=user_id, text=random.choice(_PHRASES))
    async with async_session() as session:
        db_row = await session.get(TaskNagSettings, user_id)
        if db_row is not None:
            db_row.streak_count += 1
            db_row.last_event_at = now
            db_row.last_nudge_message_id = sent.message_id
            db_row.last_nudge_sent_at = now
            await session.commit()
