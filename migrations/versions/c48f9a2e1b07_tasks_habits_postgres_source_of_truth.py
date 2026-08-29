"""tasks + habits: Postgres as source of truth (Phase 10)

Revision ID: c48f9a2e1b07
Revises: a6bc77414d12
Create Date: 2026-08-30 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c48f9a2e1b07"
down_revision: str | Sequence[str] | None = "a6bc77414d12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # tasks: notion_page_id (Notion-based identity) → id (свой суррогатный
    # ключ). SERIAL сам бэкофилит существующие строки последовательными
    # значениями.
    op.execute("ALTER TABLE tasks ADD COLUMN id SERIAL")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_pkey")
    op.execute("ALTER TABLE tasks ADD PRIMARY KEY (id)")
    op.alter_column("tasks", "notion_page_id", new_column_name="legacy_notion_id", nullable=True)

    op.add_column(
        "tasks", sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.add_column(
        "tasks",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Бэкофилл done из текущего текстового статуса — та же проверка, что
    # раньше делал DONE_STATUS_CANDIDATES/_is_done, чтобы не потерять
    # текущие отметки "выполнено" при переносе.
    op.execute(
        "UPDATE tasks SET done = true WHERE lower(status) IN ('done', 'complete', 'completed')"
    )
    op.drop_column("tasks", "status")

    op.create_table(
        "habits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("streak", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_checked", sa.Date(), nullable=True),
        sa.Column("target_frequency", sa.String(), server_default="daily", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("habits")

    op.add_column("tasks", sa.Column("status", sa.String(), nullable=True))
    op.execute("UPDATE tasks SET status = CASE WHEN done THEN 'Done' ELSE 'Not started' END")
    op.alter_column("tasks", "status", nullable=False)
    op.drop_column("tasks", "archived")
    op.drop_column("tasks", "done")

    op.alter_column("tasks", "legacy_notion_id", new_column_name="notion_page_id", nullable=False)
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_pkey")
    op.execute("ALTER TABLE tasks ADD PRIMARY KEY (notion_page_id)")
    op.drop_column("tasks", "id")
