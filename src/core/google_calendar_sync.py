"""Синхронизация Google Calendar → задачи (Phase 64). Одностороння и
"живая" — события остаются источником правды для title/due_date/
priority синхронизированной задачи (осознанное решение, подтверждено
пользователем): переименовать/перенести такую задачу вручную в
приложении можно, но следующий опрос вернёт значение из календаря
обратно. done/archived/sphere/project_id — полностью в руках
пользователя, синхронизация их не трогает никогда.

Раз в 20 минут её вызывает планировщик (см. scheduler/jobs.py) — этого
хватает для фонового обновления, но при открытии Mini App хочется не
ждать до 20 минут. maybe_sync_now (довесок) даёт этот же вызов
"по требованию" из процесса api (см. adapters/api.py::list_tasks) —
не блокируя ответ (fire-and-forget) и не чаще раза в минуту на
пользователя, иначе быстрое обновление экрана несколько раз подряд
било бы Google API впустую."""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import select

from src.core.db import async_session
from src.core.user_location import user_timezone
from src.integrations.google_calendar import GoogleAuthError, list_events, refresh_access_token
from src.models.google_calendar_account import GoogleCalendarAccount
from src.models.task import Task

logger = logging.getLogger(__name__)

# Компромисс между "видно заранее достаточно" и ограничением Google API
# на singleEvents без разумного timeMax (без границы разворачивание
# повторяющихся событий может вернуть огромный список).
_SYNC_WINDOW_DAYS_AHEAD = 60
_SYNC_WINDOW_DAYS_BEHIND = 1


def _event_to_task_fields(event: dict[str, Any], tz: ZoneInfo) -> dict[str, Any] | None:
    """Чистая функция (вынесена ради pytest, тот же приём, что
    _is_due/_should_send_nudge в прошлых фазах) — None для отменённых
    или структурно неполных событий (пропускаем, не создаём и не
    обновляем задачу)."""
    if event.get("status") == "cancelled":
        return None
    start = event.get("start") or {}
    title = event.get("summary") or "(без названия)"

    if "dateTime" in start:
        # Google отдаёт RFC3339 со своим оффсетом (или "Z" для UTC) —
        # переводим в часовой пояс пользователя и сохраняем naive (та
        # же конвенция, что и у ручных событий, см. models/task.py).
        raw = start["dateTime"].replace("Z", "+00:00")
        due_date = datetime.fromisoformat(raw).astimezone(tz).replace(tzinfo=None)
        priority = "event"
    elif "date" in start:
        due_date = datetime.combine(
            datetime.fromisoformat(start["date"]).date(), datetime.min.time()
        )
        priority = None
    else:
        return None

    return {"title": title, "due_date": due_date, "priority": priority}


async def sync_user_calendar(bot: Bot | None, user_id: int) -> None:
    """bot — None при вызове из процесса api (maybe_sync_now ниже), там
    некому и незачем поднимать отдельный Bot ради редкого уведомления
    об отозванном токене — просто пропускаем этот шаг, лог всё равно
    остаётся, а следующий плановый прогон из процесса bot (уже с живым
    ботом) сообщение пришлёт."""
    async with async_session() as session:
        account = await session.get(GoogleCalendarAccount, user_id)
    if account is None:
        return

    try:
        access_token = await refresh_access_token(account.refresh_token)
    except GoogleAuthError:
        logger.warning("Google Calendar: refresh_token отозван/просрочен (%s)", user_id)
        async with async_session() as session:
            existing = await session.get(GoogleCalendarAccount, user_id)
            if existing is not None:
                await session.delete(existing)
                await session.commit()
        if bot is not None:
            await bot.send_message(
                chat_id=user_id,
                text="Google Calendar отключился — подключите заново: /google_calendar",
            )
        return
    except Exception:
        logger.exception("Google Calendar: не удалось обновить токен (%s)", user_id)
        return

    tz = await user_timezone(user_id)
    now = datetime.now(tz)
    time_min = now - timedelta(days=_SYNC_WINDOW_DAYS_BEHIND)
    time_max = now + timedelta(days=_SYNC_WINDOW_DAYS_AHEAD)

    try:
        events = await list_events(access_token, account.calendar_id, time_min, time_max)
    except Exception:
        logger.exception("Google Calendar: не удалось получить события (%s)", user_id)
        return

    seen_event_ids: set[str] = set()
    async with async_session() as session:
        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue
            fields = _event_to_task_fields(event, tz)
            if fields is None:
                continue
            seen_event_ids.add(event_id)

            result = await session.execute(
                select(Task).where(Task.user_id == user_id, Task.google_event_id == event_id)
            )
            task = result.scalar_one_or_none()
            if task is None:
                session.add(
                    Task(
                        user_id=user_id,
                        title=fields["title"],
                        due_date=fields["due_date"],
                        priority=fields["priority"],
                        source="google_calendar",
                        google_event_id=event_id,
                        sort_order=time.time(),
                    )
                )
            else:
                task.title = fields["title"]
                task.due_date = fields["due_date"]
                task.priority = fields["priority"]

        # Синхронизированные задачи в том же окне, чьё событие пропало
        # из ответа (удалено/отменено в календаре) — архивируем, тот же
        # soft-delete принцип, что и везде в приложении. Вне окна не
        # трогаем — у нас нет свежих данных об их статусе.
        result = await session.execute(
            select(Task).where(
                Task.user_id == user_id,
                Task.source == "google_calendar",
                Task.archived.is_(False),
                Task.due_date >= time_min.replace(tzinfo=None),
                Task.due_date <= time_max.replace(tzinfo=None),
            )
        )
        for task in result.scalars().all():
            if task.google_event_id not in seen_event_ids:
                task.archived = True

        await session.commit()


_MANUAL_SYNC_COOLDOWN_SECONDS = 60
# per-процесс, в памяти — не переживает рестарт api, но это и не нужно:
# худший случай при рестарте — одна лишняя синхронизация раньше срока,
# не ошибка.
_last_manual_sync: dict[int, float] = {}


async def _sync_and_log_errors(user_id: int) -> None:
    try:
        await sync_user_calendar(None, user_id)
    except Exception:
        logger.exception(
            "Google Calendar: сбой при синхронизации по открытию Mini App (%s)", user_id
        )


def maybe_sync_now(user_id: int) -> None:
    """Дёргается из GET /miniapp/api/tasks (см. adapters/api.py) при
    каждом открытии/обновлении доски — не блокирует ответ API
    (create_task, не await: чтение задач остаётся "простым чтением без
    похода куда-либо ещё", см. комментарий у list_tasks) и не чаще раза
    в минуту на пользователя. Если Google Calendar не подключён,
    sync_user_calendar сама тихо выходит — здесь дополнительная
    проверка не нужна, лишний cooldown-словарь на неподключённых
    пользователей не стоит того, чтобы дублировать эту проверку."""
    now = time.time()
    last = _last_manual_sync.get(user_id, 0)
    if now - last < _MANUAL_SYNC_COOLDOWN_SECONDS:
        return
    _last_manual_sync[user_id] = now
    asyncio.create_task(_sync_and_log_errors(user_id))
