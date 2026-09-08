"""add authorized_user questions_topic_id

Revision ID: b7e2c4f9a103
Revises: d3f7a9c1e5b8
Create Date: 2026-09-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2c4f9a103"
down_revision: str | Sequence[str] | None = "d3f7a9c1e5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("authorized_users", sa.Column("questions_topic_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("authorized_users", "questions_topic_id")
