from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class UserProfile(Base):
    """Персональный контекст пользователя для ИИ (Phase 98) — одна строка
    на пользователя (тот же паттерн, что TaskNagSettings/
    GoogleCalendarAccount: user_id сразу primary key).

    summary — компактный текст, который подставляется в промпты
    (утренний совет, генерация задач из целей/проектов, см.
    core/user_profile.py::get_profile_summary) — NULL, пока пользователь
    не прошёл опросник (/profile, handlers/f_profile.py); все три точки
    использования должны на это проверять и деградировать мягко.

    onboarding_answers — сырые ответы опросника (JSON), не читается
    напрямую нигде кроме повторной агрегации — хранится на случай, если
    промпт агрегации позже улучшится и профиль захочется пересобрать
    заново, не гоняя пользователя по вопросам ещё раз.

    last_checked_at — когда ежедневная джоба (core/user_profile.py::
    maybe_update_profile) последний раз СМОТРЕЛА на новые заметки/задачи
    — не то же самое, что updated_at: джоба может отработать и не найти
    ничего достойного обновления, это нормальный, частый исход."""

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), primary_key=True
    )
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    onboarding_answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
