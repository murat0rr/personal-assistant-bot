"""user_id на tasks/habits/projects/goals/reminders/task_templates/
recurring_task_rules (Phase 40 — многопользовательская авторизация)

Существующие строки получают settings.telegram_user_id (владелец) —
ничего не теряется, просто становится явно "моим". Основной владелец
до сих пор мог не иметь строки в authorized_users (is_authorized его
обходит напрямую, см. src/core/auth.py) — эта миграция сначала
гарантирует ему строку там (иначе FK на новый user_id не встанет).

Revision ID: a7c3e9f1b2d4
Revises: f1a2b4c6d8e0
Create Date: 2026-08-31 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from src.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "a7c3e9f1b2d4"
down_revision: str | Sequence[str] | None = "f1a2b4c6d8e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [
    "tasks",
    "habits",
    "projects",
    "goals",
    "reminders",
    "task_templates",
    "recurring_task_rules",
]


def upgrade() -> None:
    """Upgrade schema."""
    owner_id = settings.telegram_user_id

    # 1. Владелец гарантированно есть в authorized_users — раньше
    # is_authorized() пускал его в обход этой таблицы (_is_primary_owner),
    # так что строки там могло не быть вовсе.
    op.execute(
        sa.text(
            "INSERT INTO authorized_users (telegram_user_id, added_at) "
            "VALUES (:uid, now()) ON CONFLICT (telegram_user_id) DO NOTHING"
        ).bindparams(uid=owner_id)
    )

    # 2. Добавляем user_id нулабельным, бэкофиллим владельцем, потом
    # закрываем NOT NULL + FK + индекс — стандартная последовательность
    # для добавления обязательной колонки на непустую таблицу.
    for table in _TABLES:
        op.add_column(table, sa.Column("user_id", sa.BigInteger(), nullable=True))
        op.execute(sa.text(f"UPDATE {table} SET user_id = :uid").bindparams(uid=owner_id))
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_user_id_authorized_users",
            table,
            "authorized_users",
            ["user_id"],
            ["telegram_user_id"],
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_constraint(f"fk_{table}_user_id_authorized_users", table, type_="foreignkey")
        op.drop_column(table, "user_id")
