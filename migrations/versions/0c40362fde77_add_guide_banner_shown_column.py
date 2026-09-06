"""add guide_banner_shown column

Revision ID: 0c40362fde77
Revises: e6065a7658a4
Create Date: 2026-09-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c40362fde77"
down_revision: str | Sequence[str] | None = "e6065a7658a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "authorized_users",
        sa.Column("guide_banner_shown", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Плашка "посмотреть гайд" (Phase 69, фидбек) должна появиться только
    # при САМОМ ПЕРВОМ входе в Mini App — у уже существующих на момент
    # этой миграции пользователей это первое знакомство давно позади,
    # забэкфилливаем на True, чтобы не показать её задним числом (тот же
    # принцип, что у goal_year_floor/added_at в e6065a7658a4).
    op.execute("UPDATE authorized_users SET guide_banner_shown = true")


def downgrade() -> None:
    op.drop_column("authorized_users", "guide_banner_shown")
