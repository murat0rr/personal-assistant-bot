"""chat_messages: составной PK (chat_id, message_id) вместо одного
message_id (Phase 40 — многопользовательская авторизация)

message_id уникален только внутри одного чата, не глобально — с
несколькими чатами (несколько пользователей) один message_id мог
столкнуться между разными людьми. Существующие строки — все из чата
основного владельца (до этой фазы бот был однопользовательский),
бэкофиллены его telegram_user_id (для личных чатов с ботом chat_id
численно совпадает с telegram_user_id).

Revision ID: b8d4f2a6c1e3
Revises: a7c3e9f1b2d4
Create Date: 2026-08-31 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from src.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "b8d4f2a6c1e3"
down_revision: str | Sequence[str] | None = "a7c3e9f1b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("chat_messages", sa.Column("chat_id", sa.BigInteger(), nullable=True))
    op.execute(
        sa.text("UPDATE chat_messages SET chat_id = :uid").bindparams(uid=settings.telegram_user_id)
    )
    op.alter_column("chat_messages", "chat_id", nullable=False)
    op.drop_constraint("chat_messages_pkey", "chat_messages", type_="primary")
    op.create_primary_key("chat_messages_pkey", "chat_messages", ["chat_id", "message_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("chat_messages_pkey", "chat_messages", type_="primary")
    op.create_primary_key("chat_messages_pkey", "chat_messages", ["message_id"])
    op.drop_column("chat_messages", "chat_id")
