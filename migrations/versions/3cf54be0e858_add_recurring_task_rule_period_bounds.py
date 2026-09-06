"""add recurring_task_rule period bounds

Revision ID: 3cf54be0e858
Revises: 0c40362fde77
Create Date: 2026-09-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3cf54be0e858"
down_revision: str | Sequence[str] | None = "0c40362fde77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recurring_task_rules", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("recurring_task_rules", sa.Column("period_end", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("recurring_task_rules", "period_end")
    op.drop_column("recurring_task_rules", "period_start")
