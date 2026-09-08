"""add authorized_user tasks/notes/planning topic ids

Revision ID: c4a8e1f7d205
Revises: b7e2c4f9a103
Create Date: 2026-09-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a8e1f7d205"
down_revision: str | Sequence[str] | None = "b7e2c4f9a103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("authorized_users", sa.Column("tasks_topic_id", sa.Integer(), nullable=True))
    op.add_column("authorized_users", sa.Column("notes_topic_id", sa.Integer(), nullable=True))
    op.add_column("authorized_users", sa.Column("planning_topic_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("authorized_users", "planning_topic_id")
    op.drop_column("authorized_users", "notes_topic_id")
    op.drop_column("authorized_users", "tasks_topic_id")
