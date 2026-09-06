"""add task recurring_rule_id

Revision ID: a1c2f4e8b6d7
Revises: 3cf54be0e858
Create Date: 2026-09-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c2f4e8b6d7"
down_revision: str | Sequence[str] | None = "3cf54be0e858"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("recurring_rule_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_recurring_rule_id_recurring_task_rules",
        "tasks",
        "recurring_task_rules",
        ["recurring_rule_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tasks_recurring_rule_id_recurring_task_rules", "tasks", type_="foreignkey"
    )
    op.drop_column("tasks", "recurring_rule_id")
