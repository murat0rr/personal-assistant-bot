from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class Note(Base):
    """Заметки (Phase 62) — раньше жили целиком в Notion (см.
    handlers/f_notes.py), теперь в Postgres. Простой список записей
    (не одна строка на пользователя, как у DayReview) — заметок за
    день может быть сколько угодно, тот же принцип, что у Reminder."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id. Заметки
    # сейчас доступны только владельцу (см. handlers/f_notes.py), но
    # поле сразу общее — тот же принцип, что у остальных моделей,
    # открыть на всех пользователей потом будет одной правкой гейта,
    # не миграцией.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    text: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
