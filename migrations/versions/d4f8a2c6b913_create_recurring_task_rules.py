"""create recurring_task_rules table (Phase 21)

Revision ID: d4f8a2c6b913
Revises: c72e5a1d8f4b
Create Date: 2026-08-30 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f8a2c6b913"
down_revision: str | Sequence[str] | None = "c72e5a1d8f4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "recurring_task_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("schedule_kind", sa.String(), nullable=False),
        sa.Column("schedule_value", sa.JSON(), nullable=False),
        sa.Column("sphere", sa.String(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_materialized_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_recurring_task_rules_project_id_projects",
        "recurring_task_rules",
        "projects",
        ["project_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_recurring_task_rules_project_id_projects", "recurring_task_rules", type_="foreignkey"
    )
    op.drop_table("recurring_task_rules")
