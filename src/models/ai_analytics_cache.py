from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class AiAnalyticsCache(Base):
    """Кэш текстовой ИИ-аналитики (Phase 48) — одна строка на
    пользователя, перезаписывается раз в сутки утренней джобой (см.
    scheduler/jobs.py, core/ai_analytics.py). До этой фазы
    /miniapp/api/analytics/summary дёргал Claude на каждое открытие
    вкладки "Аналитика" — теперь эндпоинт просто читает эту таблицу.
    user_id — сразу primary key: ровно одна актуальная строка на
    пользователя, отдельный суррогатный id не нужен (тот же паттерн, что
    у ScreenTime.entry_date)."""

    __tablename__ = "ai_analytics_cache"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), primary_key=True
    )
    text: Mapped[str] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
