from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String
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
    # Время утренней рассылки/вечерней рефлексии (Phase 61, команды
    # /morning и /evening) — тот же принцип, что у timezone: пусто =
    # используется текущий дефолт (8 и 21 соответственно, см.
    # scheduler/jobs.py::_job_specs). Только час, без минут — сознательно,
    # тот же принцип, что у выбора интервала /nag: кнопки, не свободный
    # ввод времени.
    morning_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evening_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Настройка "показывать утренний дайджест" (Phase 67, фидбек) — по
    # умолчанию True (сохраняет текущее поведение для всех уже
    # существующих и новых пользователей, пока явно не выключат в Mini
    # App). Гасит и саму сводку, и совет по задачам на сегодня — оба
    # шлются вместе одной джобой (см. scheduler/jobs.py::_morning_digest).
    morning_digest_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # Плашка "посмотреть гайд" в Mini App (Phase 69, фидбек) — по умолчанию
    # False (= ещё не показывали) только для НОВЫХ пользователей; у уже
    # существующих на момент этой фазы принудительно True миграцией (они
    # это первое знакомство уже прошли, показывать им плашку задним числом
    # незачем). Взводится True один раз — либо тапом по самой плашке
    # (открывает "Помощь"), либо крестиком — после этого не показывается
    # больше никогда никаким способом.
    guide_banner_shown: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Тема "Вопросы" (Phase 81, Threaded Mode — Bot API 9.3, темы теперь
    # работают и в личных чатах, не только в супергруппах) — id темы в
    # личном чате ЭТОГО пользователя с ботом, создаётся один раз лениво
    # (см. core/topics.py::get_or_create_questions_topic). NULL — ещё не
    # создавалась.
    questions_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
