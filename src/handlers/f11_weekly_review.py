from datetime import date, timedelta

from sqlalchemy import select

from src.core.config import settings
from src.core.day_reviews import entries_since
from src.core.db import async_session
from src.core.habits import list_habits
from src.models.task import Task


def build_weekly_review_text(
    tasks: list[Task],
    diary_entries: list[dict],
    habits: list[dict],
    week_start: date,
    today: date,
) -> str:
    """Чистая функция форматирования — Task/словари можно собрать без БД и
    Notion, поэтому тестируется офлайн (тот же паттерн, что build_morning_digest_text)."""
    lines = [f"🗓 Итоги недели ({week_start.strftime('%d.%m')} — {today.strftime('%d.%m')})"]

    done_this_week = [
        t
        for t in tasks
        if t.done and t.updated_at is not None and t.updated_at.date() >= week_start
    ]
    overdue = [
        t for t in tasks if not t.done and t.due_date is not None and t.due_date.date() < today
    ]
    lines.append(f"\n✅ Задачи: выполнено {len(done_this_week)}, просрочено {len(overdue)}")

    week_entries = [e for e in diary_entries if e["entry_date"] and e["entry_date"] >= week_start]
    if week_entries:
        axes = ("physical", "social", "productivity", "happiness")
        averages = []
        for axis in axes:
            values = [e[axis] for e in week_entries if e[axis] is not None]
            if values:
                averages.append(f"{axis}: {sum(values) / len(values):.1f}")
        lines.append(f"\n📔 Дневник: {len(week_entries)} записей за неделю")
        if averages:
            lines.append("Средние оценки — " + ", ".join(averages))
        highlights = [e["highlight"] for e in week_entries if e["highlight"]]
        if highlights:
            lines.append("Хайлайты:")
            lines += [f"— {h}" for h in highlights]
    else:
        lines.append("\n📔 Дневник: записей за неделю нет")

    if habits:
        lines.append("\n🔥 Привычки:")
        lines += [f"— {h['name']}: {h['streak']} дн. подряд" for h in habits]

    return "\n".join(lines)


async def build_weekly_review(user_id: int, today: date) -> str:
    week_start = today - timedelta(days=7)

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.archived.is_(False), Task.user_id == user_id)
        )
        tasks = list(result.scalars().all())

    # Дневник — только у владельца (Phase 40, см. api.py::_is_owner за
    # тем же обоснованием; с Phase 62 хранится в Postgres, но
    # ограничение по владельцу не про хранилище, оставляем как есть) —
    # для остальных просто пустой список, без ошибки.
    is_owner = user_id == settings.telegram_user_id
    diary_entries = await entries_since(user_id, week_start) if is_owner else []
    habits = await list_habits(user_id)

    return build_weekly_review_text(tasks, diary_entries, habits, week_start, today)
