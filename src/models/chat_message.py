from datetime import datetime

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from src.models.task import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    # message_id один в один уникален только ВНУТРИ чата, не глобально —
    # в личных чатах с ботом chat_id численно совпадает с
    # telegram_user_id, но это разные по смыслу поля, и одного
    # message_id больше не хватает как первичного ключа с Phase 40
    # (несколько чатов = риск столкновения id у разных пользователей).
    # Композитный ключ — тот же принцип, что message_id был раньше,
    # просто с добавленным контекстом "в каком чате".
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
