from datetime import date, datetime

from sqlalchemy import Date, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    # Postgres кэш ключуется по id страницы Notion — это и есть identity,
    # отдельный суррогатный id не нужен.
    notion_page_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
