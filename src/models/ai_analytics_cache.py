from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class AiAnalyticsCache(Base):
    """Кэш текстовой ИИ-аналитики (Phase 48) — одна строка на
    пользователя И месяц (Phase 89 — аналитика теперь листается по
    месяцам, кэш расширен вместе с ней), перезаписывается раз в сутки
    утренней джобой для ТЕКУЩЕГО месяца (см. scheduler/jobs.py,
    core/ai_analytics.py). До Phase 48 /miniapp/api/analytics/summary
    дёргал Claude на каждое открытие вкладки "Аналитика" — теперь
    эндпоинт просто читает эту таблицу (для месяца без строки — честно
    "ещё не генерировали", не тихий вызов Claude на каждый свайп).
    (user_id, year, month) — сразу составной primary key: тот же
    принцип, что раньше был у одного user_id (см. ScreenTime.entry_date)
    — отдельный суррогатный id не нужен, натуральный ключ просто шире."""

    __tablename__ = "ai_analytics_cache"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), primary_key=True
    )
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
