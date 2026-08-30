import time
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class TaskTemplate(Base):
    __tablename__ = "task_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String)
    # Ручной порядок (тот же приём, что Task.sort_order, Phase 13) — новый
    # шаблон уходит в конец без лишних правок в местах создания.
    sort_order: Mapped[float] = mapped_column(Float, default=time.time, server_default="0")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # "На какую дату ты поставил" итоговую задачу, созданную из этого
    # шаблона — не дата создания шаблона и не дата нажатия кнопки, а
    # due_date задачи. Устаревание (подсветка "давно не делал", Phase 18)
    # считается от этого поля, не от факта использования.
    last_used_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stale_after_days: Mapped[int] = mapped_column(Integer, default=14, server_default="14")
    # "manual" — создан вручную; "ai" — предложен еженедельной джобой
    # анализа частых задач (см. scheduler/jobs.py::_suggest_templates_job).
    source: Mapped[str] = mapped_column(String, default="manual", server_default="manual")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
