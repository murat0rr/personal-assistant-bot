"""create task_templates table (Phase 18)

Revision ID: e4b7f2a91c56
Revises: a3f8c1d92b6e
Create Date: 2026-08-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b7f2a91c56"
down_revision: str | Sequence[str] | None = "a3f8c1d92b6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "task_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Float(), nullable=False, server_default="0"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_used_date", sa.Date(), nullable=True),
        sa.Column("stale_after_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Затравочные шаблоны при релизе (Phase 18, §"Явные допущения") —
    # last_used_date оставляем NULL, что по _is_stale сразу подсвечивает их
    # как "давно не делал", пока пользователь ими не воспользуется хотя бы
    # раз.
    op.execute(
        """
        INSERT INTO task_templates (title, sort_order, source) VALUES
            ('Тренировка по боксу', 1000, 'manual'),
            ('Стирка', 2000, 'manual'),
            ('Продукты', 3000, 'manual'),
            ('Уборка', 4000, 'manual'),
            ('Помыть посуду', 5000, 'manual'),
            ('Вынести мусор', 6000, 'manual'),
            ('Оплатить счета', 7000, 'manual'),
            ('Полить цветы', 8000, 'manual')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("task_templates")
