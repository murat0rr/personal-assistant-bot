from datetime import date, timedelta

from src.integrations.notion import get_habit, update_habit_check


def _next_streak(current_streak: int, last_checked: date | None, today: date) -> int:
    if last_checked == today:
        return current_streak
    if last_checked == today - timedelta(days=1):
        return current_streak + 1
    return 1


async def check_habit(page_id: str, today: date) -> int:
    habit = await get_habit(page_id)
    new_streak = _next_streak(habit["streak"], habit["last_checked"], today)
    await update_habit_check(page_id, new_streak, today)
    return new_streak
