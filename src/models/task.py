import time
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
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
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False, index=True
    )
    legacy_notion_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String)
    # timestamp, а не date — гибкость для задач-событий со временем начала
    # (is_event, см. ниже). Полночь (00:00) = время не указано, обычная
    # задача на день; ненулевое время — событие с конкретным началом.
    # См. handlers/miniapp_tasks.py.
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
        Integer, ForeignKey("projects.id"), nullable=True, index=True
    )
    # Google Calendar (Phase 64) — id события в Google, вместе с
    # source="google_calendar" (поле выше) это ключ поиска "какая задача
    # отвечает этому событию" при повторном опросе (см.
    # core/google_calendar_sync.py). NULL у всех задач, не связанных с
    # календарём — тот же принцип, что у legacy_notion_id.
    google_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 65 — свободный текст, видимый только в форме редактирования
    # (Mini App). Заполняется ИИ при создании (если решит, что задаче
    # реально можно помочь конкретным советом — см.
    # integrations/claude_client.py), человеком вручную, или кнопкой
    # "сгенерировать" в самой форме. NULL — обычный случай для задач без
    # описания, тот же принцип, что у остальных nullable-полей.
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 66 — независимо от priority (важность — по-прежнему
    # "низкий"/"средний"/"высокий"). Раньше "событие" было четвёртым
    # значением priority ("event"), из-за чего важная задача не могла
    # одновременно быть событием (одно перезаписывало другое) — теперь
    # это отдельный флаг, оба состояния сочетаются свободно. Старые
    # строки с priority="event" переведены миграцией в is_event=true,
    # priority="средний" (см. migrations/).
    is_event: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Phase 77 — обратная ссылка на правило-источник (source="recurring"
    # само по себе уже проставлялось материализацией, но не позволяло
    # найти КОНКРЕТНОЕ правило от конкретного occurrence). Нужна для
    # окна редактирования по долгому нажатию на повторяющуюся задачу —
    # без неё редактировать можно было только сам occurrence, не всю
    # серию. NULL у всех задач, не рождённых из правила — тот же
    # принцип, что у остальных nullable-полей источника (google_event_id
    # и т.п.). Правило может быть удалено, а материализованные из него
    # задачи — остаться (см. core/recurring_tasks.py::archive_rule) —
    # ondelete="SET NULL", чтобы это не мешало.
    recurring_rule_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("recurring_task_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Phase 78 — длительность в минутах, для блока на "Таймлайне дня"
    # (Mini App, главный экран). NULL значит "не задана явно" — блок на
    # таймлайне тогда рисуется дефолтной высотой (см. фронтенд), ничего
    # не записывая, пока пользователь реально не растянет/не сожмёт его
    # перетаскиванием нижнего края. Имеет смысл только вместе с
    # проставленным временем в due_date (без времени задаче негде
    # рисовать блок вообще) — но отдельного ограничения на уровне БД
    # нет, как и у большинства "имеет смысл только вместе с X" полей в
    # этой модели (see is_event/google_event_id и т.п.).
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Phase 98 — "когда реально создана", не то же самое, что updated_at
    # (та меняется при любой правке/перетаскивании). Нужна профилю
    # пользователя (core/user_profile.py::maybe_update_profile) —
    # находить задачи, появившиеся с прошлой проверки, не задетые
    # недавно. До этой фазы такого поля не было вообще (в отличие от
    # Note.created_at) — существующие строки получат миграционный
    # server_default=now() на момент применения, не настоящую дату
    # создания; это ожидаемо и безвредно для профиля (только слегка
    # смещает "новизну" самых старых задач один раз, при первом прогоне
    # джобы после миграции).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Составной — под дайджест/таймлайн дня/аналитику/календарь (все
    # фильтруют по user_id+archived и диапазону due_date, см. core/tasks.py).
    # Частичный по google_event_id — под google_calendar_sync.py::_find_task_by_event,
    # ненулевой он только у задач, синхронизированных с календарём.
    # По created_at — под профиль пользователя (Phase 98,
    # core/user_profile.py), фильтрующий "задачи с прошлой проверки".
    __table_args__ = (
        Index("ix_tasks_user_id_archived_due_date", "user_id", "archived", "due_date"),
        Index(
            "ix_tasks_user_id_google_event_id",
            "user_id",
            "google_event_id",
            postgresql_where=text("google_event_id IS NOT NULL"),
        ),
        Index("ix_tasks_user_id_created_at", "user_id", "created_at"),
    )
