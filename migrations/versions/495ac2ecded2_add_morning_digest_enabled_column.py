"""add morning digest enabled column

Revision ID: 495ac2ecded2
Revises: 0fb13710d6be
Create Date: 2026-09-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "495ac2ecded2"
down_revision: str | Sequence[str] | None = "0fb13710d6be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Только morning_digest_enabled (Phase 67) — autogenerate заодно
    # предложил снести несколько индексов ix_*_user_id, не связанных с
    # этой задачей (то же известное расхождение моделей/схемы, см.
    # миграции 8012247589fb/0fb13710d6be) — сознательно не трогаем.
    op.add_column(
        "authorized_users",
        sa.Column("morning_digest_enabled", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("authorized_users", "morning_digest_enabled")
