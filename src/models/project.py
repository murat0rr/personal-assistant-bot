from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Та же таксономия, что у Task.sphere/Goal.spheres — не enum на
    # уровне БД (см. Task.sphere). Список, а не одна строка (Phase 48) —
    # проект может относиться сразу к нескольким сферам жизни; пустой
    # список — "без сферы" (было None), не каждый проект укладывается в
    # одну из 5 сфер (например бытовой проект без явной сферы) — это
    # ожидаемо, не ошибка ввода.
    spheres: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Phase 26 — отображение в стиле задач (Mini App): свой статус
    # выполнено/не выполнено (не выводится автоматически из прогресса
    # задач — управляется вручную, как у Task) и цвет из фиксированной
    # палитры 20 цветов (hex-строка, см. index.html::PROJECT_COLORS).
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
