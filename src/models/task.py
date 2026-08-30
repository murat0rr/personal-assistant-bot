import time
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String
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
    # Многопользовательность (Phase 40) — чья это задача. FK на
    # authorized_users.telegram_user_id (не users.id — своей таблицы
    # users нет, пароль-гейт из F14 стал единственным источником личности
    # пользователя). При миграции все существующие строки получили
    # settings.telegram_user_id (владелец) — ничего не потерялось.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
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
    # Phase 19/20 — глобальная классификация задачи для аналитики и целей.
    # sphere — одно из "учёба"/"работа"/"спорт"/"развитие"/"отношения" (та
    # же таксономия, что и у Goal/Project), но не enum на уровне БД —
    # список сфер сам может расшириться, не хочется миграции ради этого.
    # project_id — необязательная привязка к Project (Phase 19), задача
    # без проекта — обычный случай, не исключение.
    sphere: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
