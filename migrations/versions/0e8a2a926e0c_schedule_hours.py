"""schedule hours

Revision ID: 0e8a2a926e0c
Revises: 2c4338ecdfa6
Create Date: 2026-09-02 23:27:18.251795

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0e8a2a926e0c"
down_revision: str | Sequence[str] | None = "2c4338ecdfa6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Автогенерация заодно предложила снять индексы ix_*_user_id на
# habits/projects/recurring_task_rules/reminders/task_templates/tasks —
# то же расхождение модели/БД, не связанное с этой фазой, что уже
# встречалось в Phase 48/50/54/59 миграциях. Не включаем сюда.


def upgrade() -> None:
    op.add_column("authorized_users", sa.Column("morning_hour", sa.Integer(), nullable=True))
    op.add_column("authorized_users", sa.Column("evening_hour", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("authorized_users", "evening_hour")
    op.drop_column("authorized_users", "morning_hour")
