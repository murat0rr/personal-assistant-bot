import time
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    # Postgres — единственный источник правды (Phase 10): раньше строка
    # ключевалась id страницы Notion, теперь у задачи свой суррогатный id.
    # legacy_notion_id оставлен только для истории/отладки, в логике не
    # используется.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    legacy_notion_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String)
    # timestamp, а не date — гибкость для задач-событий со временем начала
    # (приоритет "event"). Полночь (00:00) = время не указано, обычная
    # задача на день; ненулевое время — событие с конкретным началом. Без
    # отдельного булева флага под один частный случай — см. handlers/miniapp_tasks.py.
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    priority: Mapped[str | None] = mapped_column(String, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Ручной порядок (Phase 13) — дробная индексация: новая задача получает
    # time.time() (заведомо больше всех существующих — "в конец"), а
    # перетаскивание между двумя соседями просто берёт среднее их
    # sort_order, не трогая никого третьего. default=time.time — сама
    # функция, не вызов: SQLAlchemy зовёт её при каждой вставке новой строки.
    sort_order: Mapped[float] = mapped_column(Float, default=time.time, server_default="0")
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
