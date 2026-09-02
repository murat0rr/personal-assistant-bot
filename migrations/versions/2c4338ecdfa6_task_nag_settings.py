"""task nag settings

Revision ID: 2c4338ecdfa6
Revises: 7d586fa9ceee
Create Date: 2026-09-02 22:53:24.728690

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2c4338ecdfa6"
down_revision: str | Sequence[str] | None = "7d586fa9ceee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Автогенерация заодно предложила снять индексы ix_*_user_id на
# habits/projects/recurring_task_rules/reminders/task_templates/tasks —
# то же расхождение модели/БД, не связанное с этой фазой, что уже
# встречалось в Phase 48/50/54 миграциях. Не включаем сюда.


def upgrade() -> None:
    op.create_table(
        "task_nag_settings",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=True),
        sa.Column("streak_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_nudge_message_id", sa.Integer(), nullable=True),
        sa.Column("last_nudge_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("task_nag_settings")
