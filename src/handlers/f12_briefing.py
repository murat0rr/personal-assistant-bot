from datetime import UTC, date, datetime, timedelta

from src.core.chat_watch import digest_summary_lines
from src.core.habits import list_habits
from src.handlers.f5_morning_digest import build_morning_digest
from src.integrations.weather import get_weather_summary


def build_briefing_text(
    tasks_text: str,
    weather_line: str | None,
    habits: list[dict],
    chat_watch_lines: list[str] | None = None,
) -> str:
    """Чистая функция-компоновщик — тестируется офлайн, как build_morning_digest_text."""
    parts = [tasks_text]

    if weather_line:
        parts.append(weather_line)

    if habits:
        habit_lines = "\n".join(f"— {h['name']}: {h['streak']} дн." for h in habits)
        parts.append(f"🔥 Привычки:\n{habit_lines}")

    # Из наблюдаемых каналов/групп (Phase 99) — только если за последние
    # сутки реально появились новые заметки, см. core/chat_watch.py::digest_summary_lines.
    if chat_watch_lines:
        parts.append("📡 Из каналов (24ч):\n" + "\n".join(chat_watch_lines))

    return "\n\n".join(parts)


async def build_morning_briefing(user_id: int, today: date) -> str:
    tasks_text = await build_morning_digest(user_id, today)
    weather_line = await get_weather_summary(user_id)
    habits = await list_habits(user_id)
    chat_watch_lines = await digest_summary_lines(user_id, datetime.now(UTC) - timedelta(hours=24))

    return build_briefing_text(tasks_text, weather_line, habits, chat_watch_lines)
