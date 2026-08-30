from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Та же таксономия, что у Task.sphere/Goal.sphere — не enum на уровне
    # БД (см. Task.sphere), и, в отличие от них, может быть пустой: не
    # каждый проект укладывается в одну из 5 сфер (например бытовой
    # проект без явной сферы) — это ожидаемо, не ошибка ввода.
    sphere: Mapped[str | None] = mapped_column(String, nullable=True)
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
