from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.task import Base


class Habit(Base):
    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id за подробным
    # комментарием, тот же принцип везде.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String)
    streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_checked: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_frequency: Mapped[str] = mapped_column(String, default="daily", server_default="daily")
