"""authorized_users.latitude/longitude/timezone/location_label (Phase 39)

Revision ID: f1a2b4c6d8e0
Revises: e8a3c5f17d2b
Create Date: 2026-08-31 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b4c6d8e0"
down_revision: str | Sequence[str] | None = "e8a3c5f17d2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("authorized_users", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("authorized_users", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("authorized_users", sa.Column("timezone", sa.String(), nullable=True))
    op.add_column("authorized_users", sa.Column("location_label", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("authorized_users", "location_label")
    op.drop_column("authorized_users", "timezone")
    op.drop_column("authorized_users", "longitude")
    op.drop_column("authorized_users", "latitude")
