"""drop project color column

Revision ID: ff2ba2c15e7b
Revises: 495ac2ecded2
Create Date: 2026-09-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff2ba2c15e7b"
down_revision: str | Sequence[str] | None = "495ac2ecded2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Только color (Phase 67, фидбек: убрать цвет у всех проектов и
    # целей полностью, включая БД) — autogenerate заодно предложил снести
    # несколько индексов ix_*_user_id, не связанных с этой задачей (то
    # же известное расхождение моделей/схемы, см. миграции
    # 8012247589fb/0fb13710d6be/495ac2ecded2) — сознательно не трогаем.
    op.drop_column("projects", "color")


def downgrade() -> None:
    op.add_column("projects", sa.Column("color", sa.String(), nullable=True))
