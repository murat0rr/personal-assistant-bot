from datetime import date, timedelta

from src.core.habits import get_habit, update_habit_check


def _next_streak(current_streak: int, last_checked: date | None, today: date) -> int:
    if last_checked == today:
        return current_streak
    if last_checked == today - timedelta(days=1):
        return current_streak + 1
    return 1


async def check_habit(habit_id: int, today: date) -> int:
    habit = await get_habit(habit_id)
    new_streak = _next_streak(habit["streak"], habit["last_checked"], today)
    await update_habit_check(habit_id, new_streak, today)
    return new_streak
