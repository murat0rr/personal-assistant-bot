from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.models.task import Base


class ScreenTime(Base):
    __tablename__ = "screen_time"

    # Один дневной итог на дату — вебхук от Tasker апсертит по entry_date,
    # отдельный суррогатный id не нужен (тот же паттерн, что у Task).
    entry_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_minutes: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
