from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class DayReview(Base):
    """Ревью дня (Phase 48) — текстовый ИИ-саммари вечерней рефлексии
    дневника (см. integrations/claude_client.py::summarize_diary), уже
    считается в конце вечернего опроса (handlers/f4_diary.py::_finish) и
    сохраняется в Notion, но раньше нигде не отображался обратно
    пользователю. Дублируем его сюда в момент, когда он и так уже
    посчитан — календарь Mini App читает ревью прошедших дней отсюда, не
    дёргая Claude заново при каждом открытии (см. core/day_reviews.py).
    Notion остаётся источником правды для оценок дня и "особенности" —
    их эта таблица не хранит."""

    __tablename__ = "day_reviews"
    __table_args__ = (UniqueConstraint("user_id", "review_date", name="uq_day_reviews_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    review_date: Mapped[date] = mapped_column(Date, nullable=False)
    text: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
