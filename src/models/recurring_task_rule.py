from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class RecurringTaskRule(Base):
    __tablename__ = "recurring_task_rules"

    # Правило, а не миллион строк задач заранее (Phase 21 требование) —
    # реальная Task-строка материализуется только на факт наступившего
    # дня (см. scheduler/jobs.py::_materialize_recurring_tasks_job), и
    # только одна на occurrence: last_materialized_date — та же защита
    # от повторной материализации в один день, что last_fired_date у
    # Reminder (schedule_kind/schedule_value — тот же паттерн оттуда же).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String)
    schedule_kind: Mapped[str] = mapped_column(String)
    schedule_value: Mapped[dict] = mapped_column(JSON)
    sphere: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_materialized_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
