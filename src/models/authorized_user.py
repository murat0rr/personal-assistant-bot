from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.task import Base


class AuthorizedUser(Base):
    __tablename__ = "authorized_users"

    # Telegram user id может превышать диапазон обычного 32-битного Integer —
    # BigInteger с запасом.
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Геопозиция и часовой пояс (Phase 39, команда /timezone) — заполняются,
    # когда пользователь один раз делится геопозицией в Telegram; до этого
    # все три поля пустые, приложение падает на статичный settings.timezone/
    # settings.weather_city из .env. Координаты нужны отдельно от timezone
    # (не только для расчёта зоны) — погода строится сразу по ним, без
    # похода в geocoding по имени города.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    location_label: Mapped[str | None] = mapped_column(String, nullable=True)
