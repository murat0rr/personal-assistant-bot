"""add task duration_minutes

Revision ID: d3f7a9c1e5b8
Revises: a1c2f4e8b6d7
Create Date: 2026-09-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3f7a9c1e5b8"
down_revision: str | Sequence[str] | None = "a1c2f4e8b6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("duration_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "duration_minutes")
