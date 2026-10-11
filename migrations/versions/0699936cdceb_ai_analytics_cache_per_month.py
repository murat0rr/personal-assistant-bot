"""ai analytics cache per month

Phase 89 — аналитика теперь листается по месяцам (банер-свайп наверху
вкладки "Аналитика"); кэш ИИ-сводки (ai_analytics_cache) был one-row-
per-user, стал one-row-per-user-per-month. Таблица — чистый
перегенерируемый кэш (ежедневная джоба переписывает её целиком),
поэтому мигрируем через drop+create, а не backfill: единственная
старая строка на пользователя не несёт различимой информации о том, к
какому месяцу она относилась (конструктивно всегда была "последний
месяц"), backfill был бы угадыванием. Потеря кэша не критична —
аварийный фолбэк в эндпоинте мгновенно восстановит текущий месяц,
остальные — по явному "сгенерировать" (см. SPEC.md Phase 89).

Revision ID: 0699936cdceb
Revises: 550b5ab1c434
Create Date: 2026-10-11 16:29:26.448354

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0699936cdceb"
down_revision: str | Sequence[str] | None = "550b5ab1c434"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("ai_analytics_cache")
    op.create_table(
        "ai_analytics_cache",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("user_id", "year", "month"),
    )


def downgrade() -> None:
    op.drop_table("ai_analytics_cache")
    op.create_table(
        "ai_analytics_cache",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
