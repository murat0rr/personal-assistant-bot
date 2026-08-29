from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session
from src.integrations.notion import DONE_STATUS_CANDIDATES, list_diary_entries, list_habits
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
        if t.status.lower() in DONE_STATUS_CANDIDATES
        and t.updated_at is not None
        and t.updated_at.date() >= week_start
    ]
    overdue = [
        t
        for t in tasks
        if t.status.lower() not in DONE_STATUS_CANDIDATES
        and t.due_date is not None
        and t.due_date < today
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


async def build_weekly_review() -> str:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    week_start = today - timedelta(days=7)

    async with async_session() as session:
        result = await session.execute(select(Task))
        tasks = list(result.scalars().all())

    diary_entries = await list_diary_entries() if settings.notion_diary_db_id else []
    habits = await list_habits() if settings.notion_habits_db_id else []

    return build_weekly_review_text(tasks, diary_entries, habits, week_start, today)
