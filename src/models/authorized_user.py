from datetime import datetime

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from src.models.task import Base


class AuthorizedUser(Base):
    __tablename__ = "authorized_users"

    # Telegram user id может превышать диапазон обычного 32-битного Integer —
    # BigInteger с запасом.
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
