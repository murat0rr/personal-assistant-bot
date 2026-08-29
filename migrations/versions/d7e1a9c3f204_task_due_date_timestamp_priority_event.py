"""tasks.due_date: date -> timestamp (событие со временем начала)

Revision ID: d7e1a9c3f204
Revises: c48f9a2e1b07
Create Date: 2026-08-31 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e1a9c3f204"
down_revision: str | Sequence[str] | None = "c48f9a2e1b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # date -> timestamp: существующие значения переезжают на полночь того же
    # дня (== "время не указано" по конвенции, см. handlers/miniapp_tasks.py).
    op.execute("ALTER TABLE tasks ALTER COLUMN due_date TYPE timestamp USING due_date::timestamp")


def downgrade() -> None:
    """Downgrade schema."""
    # Время (если было проставлено на событии) теряется при откате — это
    # ожидаемо для downgrade на более старую схему, которая его не хранила.
    op.execute("ALTER TABLE tasks ALTER COLUMN due_date TYPE date USING due_date::date")
