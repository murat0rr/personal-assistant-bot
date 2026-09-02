"""diary and notes on postgres

Phase 62 — дневник и заметки переезжают с Notion на Postgres. day_reviews
получает поля, которые раньше жили только в Notion (physical/social/
productivity/happiness/highlight/reflection), text (саммари) становится
опциональным — день с одними оценками, без highlight/reflection для
саммари, теперь валидный случай (см. src/models/day_review.py). Новая
таблица notes — заметки (раньше в Notion, см. src/models/note.py).

(Пропущены предложенные autogenerate'ом drop_index на ix_*_user_id —
существующий дрифт между моделями и БД, не связанный с этой фазой, тот
же случай, что и в прошлых миграциях этой сессии.)

Revision ID: 0898ba222963
Revises: 0e8a2a926e0c
Create Date: 2026-09-02 23:44:22.824942

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0898ba222963"
down_revision: str | Sequence[str] | None = "0e8a2a926e0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("day_reviews", sa.Column("physical", sa.Integer(), nullable=True))
    op.add_column("day_reviews", sa.Column("social", sa.Integer(), nullable=True))
    op.add_column("day_reviews", sa.Column("productivity", sa.Integer(), nullable=True))
    op.add_column("day_reviews", sa.Column("happiness", sa.Integer(), nullable=True))
    op.add_column("day_reviews", sa.Column("highlight", sa.String(), nullable=True))
    op.add_column("day_reviews", sa.Column("reflection", sa.String(), nullable=True))
    op.alter_column("day_reviews", "text", existing_type=sa.VARCHAR(), nullable=True)


def downgrade() -> None:
    op.alter_column("day_reviews", "text", existing_type=sa.VARCHAR(), nullable=False)
    op.drop_column("day_reviews", "reflection")
    op.drop_column("day_reviews", "highlight")
    op.drop_column("day_reviews", "happiness")
    op.drop_column("day_reviews", "productivity")
    op.drop_column("day_reviews", "social")
    op.drop_column("day_reviews", "physical")
    op.drop_table("notes")
