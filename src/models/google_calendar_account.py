from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class GoogleCalendarAccount(Base):
    """Подключение Google Calendar (Phase 64, команда /google_calendar)
    — одна строка на пользователя (тот же паттерн, что TaskNagSettings:
    user_id сразу primary key). Хранит только refresh_token — access_token
    короткоживущий, получается заново на каждый опрос (см.
    integrations/google_calendar.py::refresh_access_token), сохранять
    его смысла нет."""

    __tablename__ = "google_calendar_accounts"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), primary_key=True
    )
    refresh_token: Mapped[str] = mapped_column(String)
    # Только primary на первой версии (осознанное решение, см. PLAN.md)
    # — поле уже здесь, чтобы выбор календаря потом был правкой одной
    # строки, не миграцией.
    calendar_id: Mapped[str] = mapped_column(String, default="primary", server_default="primary")
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
