from src.models.ai_analytics_cache import AiAnalyticsCache
from src.models.authorized_user import AuthorizedUser
from src.models.chat_message import ChatMessage
from src.models.day_review import DayReview
from src.models.habit import Habit
from src.models.note import Note
from src.models.project import Project
from src.models.recurring_task_rule import RecurringTaskRule
from src.models.reminder import Reminder
from src.models.screen_time import ScreenTime
from src.models.task import Base, Task
from src.models.task_nag import TaskNagSettings
from src.models.task_template import TaskTemplate

__all__ = [
    "Base",
    "Task",
    "Habit",
    "ChatMessage",
    "Reminder",
    "ScreenTime",
    "AuthorizedUser",
    "TaskTemplate",
    # Project и Goal — одна сущность (Phase 54): Project.tier=None —
    # обычный проект, иначе — бывшая цель. Отдельной модели Goal больше
    # нет (см. src/core/goals.py — тонкий адаптер над projects.py).
    "Project",
    "RecurringTaskRule",
    "DayReview",
    "AiAnalyticsCache",
    "TaskNagSettings",
    "Note",
]
