"""google calendar accounts

Phase 64 — интеграция с Google Calendar. Новая таблица
google_calendar_accounts (одна строка на пользователя — refresh_token,
какой календарь синхронизируем) и новая колонка tasks.google_event_id
(ключ поиска "какая задача отвечает этому событию" при повторном
опросе, см. core/google_calendar_sync.py).

(Пропущены предложенные autogenerate'ом drop_index на ix_*_user_id —
существующий дрифт между моделями и БД, не связанный с этой фазой, тот
же случай, что и в прошлых миграциях этой сессии.)

Revision ID: 8b521e971ab2
Revises: 0898ba222963
Create Date: 2026-09-05 11:31:28.698007

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b521e971ab2"
down_revision: str | Sequence[str] | None = "0898ba222963"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_calendar_accounts",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=False),
        sa.Column("calendar_id", sa.String(), server_default="primary", nullable=False),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.add_column("tasks", sa.Column("google_event_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "google_event_id")
    op.drop_table("google_calendar_accounts")
