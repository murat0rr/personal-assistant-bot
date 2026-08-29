from src.core.habits import list_habits
from src.handlers.f5_morning_digest import build_morning_digest
from src.integrations.weather import get_weather_summary


def build_briefing_text(tasks_text: str, weather_line: str | None, habits: list[dict]) -> str:
    """Чистая функция-компоновщик — тестируется офлайн, как build_morning_digest_text."""
    parts = [tasks_text]

    if weather_line:
        parts.append(weather_line)

    if habits:
        habit_lines = "\n".join(f"— {h['name']}: {h['streak']} дн." for h in habits)
        parts.append(f"🔥 Привычки:\n{habit_lines}")

    return "\n\n".join(parts)


async def build_morning_briefing() -> str:
    tasks_text = await build_morning_digest()
    weather_line = await get_weather_summary()
    habits = await list_habits()

    return build_briefing_text(tasks_text, weather_line, habits)
