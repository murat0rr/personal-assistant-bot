from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.models.task import Base


class TaskNagSettings(Base):
    """Намёки о незакрытых задачах (Phase 59, команда /nag) — одна
    строка на пользователя (тот же паттерн, что AiAnalyticsCache:
    user_id сразу primary key, отдельный суррогатный id не нужен).

    Формула эскалации (подтверждена пользователем): при включении с
    интервалом X часов — 1-й намёк через X часов бездействия, 2-й —
    ещё через (X+1) час после первого, 3-й — через (X+2) после
    второго и т.д. (см. core/handlers/f_task_nag.py::check_and_nudge).
    """

    __tablename__ = "task_nag_settings"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # N — сколько намёков подряд уже отправлено с последнего выполнения
    # задачи, обнуляется в 0 при любом выполнении (см.
    # f_task_nag.py::record_task_completion).
    streak_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Точка отсчёта для формулы X+N — сдвигается на "сейчас" и при
    # включении фичи, и при выполнении задачи (вместе с обнулением N),
    # и при каждом отправленном намёке (вместе с N += 1). Следующий
    # порог всегда считается от последнего из этих трёх событий.
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Для автоудаления сообщения через 59 минут — НЕ то же самое, что
    # last_event_at: если между отправкой намёка и его удалением
    # пользователь успел закрыть задачу, last_event_at уже сдвинется
    # вперёд, а ЭТО сообщение всё равно должно быть удалено по своему
    # собственному таймеру, независимо от streak_count/enabled.
    last_nudge_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_nudge_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
