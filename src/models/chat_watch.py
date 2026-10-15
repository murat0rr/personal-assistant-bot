from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class WatchedChat(Base):
    """Канал или группа, зарегистрированная авторизованным пользователем
    для пассивного наблюдения через Bot API (Phase 99, заменяет
    MTProto-подход Phase 87) — бот должен быть добавлен туда самим
    пользователем (в канал — админом, в группу — участником), иначе
    регистрация не проходит (handlers/f_chat_watch.py::_resolve_chat_type).
    custom_prompt пишет сам пользователь при регистрации — это
    доверенная инструкция, в отличие от текста сообщений самого чата
    (см. core/prompts.py::chat_watch_system_prompt). chat_type —
    "channel" | "group"."""

    __tablename__ = "watched_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    # id чата ровно в том виде, в котором его отдаёт Bot API
    # (message.chat.id / message.forward_from_chat.id).
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    chat_type: Mapped[str] = mapped_column(String, nullable=False)  # "group" | "channel"
    custom_prompt: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    batch_size_threshold: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    batch_timeout_hours: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Повторная регистрация того же чата — обновление промпта, не
    # дубликат строки (см. core/chat_watch.py::register_watched_chat).
    __table_args__ = (
        UniqueConstraint("user_id", "telegram_chat_id", name="uq_watched_chat_user_chat"),
    )


class WatchedMessage(Base):
    """Буфер сообщений наблюдаемого чата, ждущих батч-обработки (Phase
    87). Минимальное хранение о чужих людях — только отображаемое
    имя/username и id отправителя, без био/фото/онлайн-статуса (см.
    обсуждение фичи). Удаляются целиком сразу после успешной обработки
    батча (core/chat_watch.py::process_batch) — сырой текст третьих лиц
    не хранится дольше одного батча."""

    __tablename__ = "watched_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watched_chat_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("watched_chats.id", ondelete="CASCADE"), nullable=False
    )
    sender_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_display_name: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    # Время самого сообщения в Телеграме, не время приёма ботом —
    # используется и для сортировки транскрипта, и для time-триггера
    # батча (MIN(sent_at) против batch_timeout_hours).
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Обслуживает и size-триггер (COUNT(*) WHERE watched_chat_id=...), и
    # time-триггер (MIN(sent_at) WHERE watched_chat_id=...).
    __table_args__ = (Index("ix_watched_messages_chat_sent", "watched_chat_id", "sent_at"),)
