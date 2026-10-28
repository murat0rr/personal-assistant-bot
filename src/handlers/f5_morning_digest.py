from datetime import date

from sqlalchemy import select

from src.core.db import async_session
from src.models.task import Task


def _task_time(task: Task) -> str | None:
    # Полночь — конвенция "время не указано" (та же, что
    # handlers/miniapp_tasks.py::_task_time — не импортируется напрямую,
    # этот модуль исторически не зависел от miniapp_tasks, не стоило
    # заводить такую связь ради одной маленькой чистой функции).
    if task.due_date is None or (task.due_date.hour == 0 and task.due_date.minute == 0):
        return None
    return task.due_date.strftime("%H:%M")


def _format_item(task: Task) -> str:
    # Phase 98, фидбек по дайджесту — время (если есть) и значок 🔁 у
    # повторяющихся задач (source="recurring", проставляется
    # материализацией, см. core/recurring_tasks.py) — раньше оба
    # признака были в БД, но нигде не показывались в тексте дайджеста.
    bits = []
    time_part = _task_time(task)
    if time_part:
        bits.append(time_part)
    if task.source == "recurring":
        bits.append("🔁")
    prefix = (" ".join(bits) + " ") if bits else ""
    return f"— {prefix}{task.title}"


def build_morning_digest_text(tasks: list[Task], today: date) -> str:
    """Чистая функция форматирования — Task можно создать без сессии БД
    (обычный Python-объект), поэтому тестируется офлайн. due_date — теперь
    timestamp (см. Task), поэтому сравниваем именно дату, не время.

    Phase 98 — "На сегодня" разделено на события (is_event=True — сюда
    попадают и ручные события, и всё из Google Calendar, см.
    core/google_calendar_sync.py) и обычные задачи: раньше оба вида были
    в одном неразличимом списке по одному заголовку, хотя у событий уже
    есть осмысленное время начала в due_date.

    Фидбек #18/#19 (2026-10-28, дубликат — просьба повторена дважды) —
    просроченные задачи больше НЕ показываются в утреннем сообщении
    вообще, только сегодняшние. Данные никуда не пропадают (просроченное
    всё ещё видно в Инбоксе Mini App, см. miniapp_tasks.py) — убрана
    только эта секция конкретно из утреннего текста."""
    due_today = [t for t in tasks if t.due_date is not None and t.due_date.date() == today]
    events_today = sorted((t for t in due_today if t.is_event), key=lambda t: t.due_date)
    tasks_today = [t for t in due_today if not t.is_event]

    if not due_today:
        return "🌅 Доброе утро! На сегодня активных задач нет."

    lines = ["🌅 Доброе утро!"]
    if events_today:
        lines.append("\n🗓 События:")
        lines += [_format_item(t) for t in events_today]
    if tasks_today:
        lines.append("\n📌 На сегодня:")
        lines += [_format_item(t) for t in tasks_today]
    return "\n".join(lines)


async def build_morning_digest(user_id: int, today: date) -> str:
    # today приходит от вызывающего (Phase 40 — у каждого пользователя
    # своя джоба в своём часовом поясе, см. scheduler/jobs.py), а не
    # считается тут по глобальному settings.timezone.
    async with async_session() as session:
        query = select(Task).where(
            Task.due_date.is_not(None),
            Task.done.is_(False),
            Task.archived.is_(False),
            Task.user_id == user_id,
        )
        result = await session.execute(query)
        tasks = list(result.scalars().all())

    return build_morning_digest_text(tasks, today)
