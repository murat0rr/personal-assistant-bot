from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    # Та же таксономия, что Task.sphere/Project.spheres — не enum на
    # уровне БД (см. Task.sphere). Список, а не одна строка (Phase 48) —
    # цель может относиться сразу к нескольким сферам жизни. У целей, в
    # отличие от проектов, список не может быть пустым (проверяется в
    # API-слое, см. api.py::RequiredSpheresField) — весь смысл этой
    # сущности — сгруппировать намерения по жизненным сферам для будущей
    # аналитики.
    spheres: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    # "weekly" | "monthly" | "quarterly" | "yearly" | "5year"
    tier: Mapped[str] = mapped_column(String)
    # Для "5year" оба поля NULL — нет естественной границы периода,
    # которую имело бы смысл сбрасывать (см. SPEC.md/PLAN.md, Phase 20).
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    text: Mapped[str] = mapped_column(String)
    # Phase 26 — отображение в стиле задач (Mini App): статус выполнено/
    # не выполнено (ручной, как у Task) + возможность архивировать
    # (та же корзина, что у задач/проектов/шаблонов).
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
