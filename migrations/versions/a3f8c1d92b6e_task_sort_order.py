"""tasks.sort_order — ручной порядок (Phase 13)

Revision ID: a3f8c1d92b6e
Revises: d7e1a9c3f204
Create Date: 2026-09-02 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f8c1d92b6e"
down_revision: str | Sequence[str] | None = "d7e1a9c3f204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tasks",
        sa.Column("sort_order", sa.Float(), nullable=False, server_default="0"),
    )
    # Бэкофилл по старому эффективному порядку (приоритет, затем id), чтобы
    # видимый порядок в момент деплоя не дёрнулся — задачи в рамках одного
    # дня и группы (событие/обычная) получают возрастающий sort_order в
    # том же относительном порядке, в каком уже показывались.
    op.execute(
        """
        UPDATE tasks t
        SET sort_order = sub.rn * 1000
        FROM (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY due_date::date, (priority = 'event')
                       ORDER BY
                           CASE priority
                               WHEN 'высокий' THEN 0
                               WHEN 'event' THEN 0
                               WHEN 'средний' THEN 1
                               WHEN 'низкий' THEN 2
                               ELSE 3
                           END,
                           -- у обычных задач due_date в рамках партиции
                           -- одинаковый (либо совпадающая полночь, либо
                           -- NULL) — не влияет; у событий он же несёт
                           -- время начала, поэтому корректно сохраняет их
                           -- прежний порядок по времени, а не по id.
                           due_date,
                           id
                   ) AS rn
            FROM tasks
        ) sub
        WHERE t.id = sub.id
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tasks", "sort_order")
