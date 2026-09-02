from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class DayReview(Base):
    """Дневник дня (Phase 48, полный источник правды с Phase 62) —
    оценки (physical/social/productivity/happiness), текст
    highlight/reflection вечернего опроса (handlers/f4_diary.py::_finish)
    и текстовый ИИ-саммари этого же опроса (integrations/claude_client.py::
    summarize_diary). До Phase 62 источником правды для оценок/текста
    highlight/reflection был Notion, эта таблица дублировала только
    готовый саммари как кэш для календаря Mini App — теперь дублировать
    нечего, дневник целиком здесь (см. core/day_reviews.py), Notion
    больше не используется (интеграция ещё в репозитории, но неактивна,
    удаляется отдельной фазой)."""

    __tablename__ = "day_reviews"
    __table_args__ = (UniqueConstraint("user_id", "review_date", name="uq_day_reviews_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    review_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Саммари теперь необязателен (Phase 62) — раньше строка вообще не
    # создавалась без него (см. старую f4_diary.py::_finish: `if summary:
    # await save_review(...)`), но день с одними оценками, без
    # highlight/reflection текста для саммари — валидный случай, который
    # раньше просто терялся (жил только в Notion).
    text: Mapped[str | None] = mapped_column(String, nullable=True)
    # Оценки дня (шкала 1-3, см. handlers/f4_diary.py) и текстовые поля
    # опроса (Phase 62) — раньше жили только в Notion.
    physical: Mapped[int | None] = mapped_column(Integer, nullable=True)
    social: Mapped[int | None] = mapped_column(Integer, nullable=True)
    productivity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    happiness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    highlight: Mapped[str | None] = mapped_column(String, nullable=True)
    reflection: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
