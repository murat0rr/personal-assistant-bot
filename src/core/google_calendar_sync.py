"""Синхронизация Google Calendar → задачи (Phase 64). Одностороння и
"живая" — события остаются источником правды для title/due_date/
priority синхронизированной задачи (осознанное решение, подтверждено
пользователем): переименовать/перенести такую задачу вручную в
приложении можно, но следующий опрос вернёт значение из календаря
обратно. done/archived/sphere/project_id — полностью в руках
пользователя, синхронизация их не трогает никогда."""

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


async def sync_user_calendar(bot: Bot, user_id: int) -> None:
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
