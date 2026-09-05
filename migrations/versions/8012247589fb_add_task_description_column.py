"""add task description column

Revision ID: 8012247589fb
Revises: 8b521e971ab2
Create Date: 2026-09-05 16:28:02.289698

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8012247589fb"
down_revision: str | Sequence[str] | None = "8b521e971ab2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Только description (Phase 65) — autogenerate заодно предложил
    # снести несколько индексов ix_*_user_id, не связанных с этой
    # задачей (расхождение между моделями и реальной схемой, накопленное
    # раньше) — сознательно не трогаем их в этой миграции.
    op.add_column("tasks", sa.Column("description", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "description")
