"""watched chats and messages

Phase 87 — наблюдение за внешними чатами через MTProto: владелец
регистрирует личную переписку или чужую группу (куда бота как Bot API
не добавить), сообщения копятся в watched_messages батчем и разбираются
Claude по custom_prompt на заметки/задачи, после чего буфер удаляется
(минимальное хранение третьих лиц) — только CREATE TABLE/INDEX, без
изменения существующих данных.

Revision ID: 550b5ab1c434
Revises: b8ab5e137d31
Create Date: 2026-10-11 14:36:43.886613

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "550b5ab1c434"
down_revision: str | Sequence[str] | None = "b8ab5e137d31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watched_chats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("chat_type", sa.String(), nullable=False),
        sa.Column("custom_prompt", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("batch_size_threshold", sa.Integer(), server_default="100", nullable=False),
        sa.Column("batch_timeout_hours", sa.Integer(), server_default="5", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "telegram_chat_id", name="uq_watched_chat_user_chat"),
    )
    op.create_table(
        "watched_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("watched_chat_id", sa.Integer(), nullable=False),
        sa.Column("sender_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_display_name", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["watched_chat_id"], ["watched_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_watched_messages_chat_sent", "watched_messages", ["watched_chat_id", "sent_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_watched_messages_chat_sent", table_name="watched_messages")
    op.drop_table("watched_messages")
    op.drop_table("watched_chats")
