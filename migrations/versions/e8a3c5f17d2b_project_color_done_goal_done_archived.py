"""project.color/done + goal.done/archived (Phase 26)

Revision ID: e8a3c5f17d2b
Revises: d4f8a2c6b913
Create Date: 2026-08-30 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8a3c5f17d2b"
down_revision: str | Sequence[str] | None = "d4f8a2c6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("projects", sa.Column("color", sa.String(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "goals", sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.add_column(
        "goals",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("goals", "archived")
    op.drop_column("goals", "done")
    op.drop_column("projects", "done")
    op.drop_column("projects", "color")
