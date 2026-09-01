"""day reviews, ai analytics cache, project/goal spheres array

Revision ID: e409307aca59
Revises: b8d4f2a6c1e3
Create Date: 2026-09-01 20:59:04.229017

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e409307aca59"
down_revision: str | Sequence[str] | None = "b8d4f2a6c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Автогенерация заодно предложила снять индексы ix_*_user_id на
# habits/recurring_task_rules/reminders/task_templates/tasks/goals/
# projects — расхождение с моделями, не связанное с этой фазой (эта
# фаза не трогает ни одну из этих таблиц структурно, кроме добавления
# spheres). Не включаем эти дропы сюда — отдельный вопрос, не смешиваем
# с Phase 48.


def upgrade() -> None:
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
    op.create_table(
        "day_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "review_date", name="uq_day_reviews_user_date"),
    )

    # Project.sphere/Goal.sphere (одна строка) -> spheres (массив) —
    # добавляем новую колонку, переносим существующие значения, снимаем
    # старую. У goals sphere была NOT NULL, так что после UPDATE ...
    # WHERE sphere IS NOT NULL все строки покрыты безусловно.
    op.add_column(
        "projects",
        sa.Column("spheres", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
    )
    op.execute("UPDATE projects SET spheres = ARRAY[sphere] WHERE sphere IS NOT NULL")
    op.drop_column("projects", "sphere")

    op.add_column(
        "goals",
        sa.Column("spheres", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
    )
    op.execute("UPDATE goals SET spheres = ARRAY[sphere] WHERE sphere IS NOT NULL")
    op.drop_column("goals", "sphere")


def downgrade() -> None:
    op.add_column("goals", sa.Column("sphere", sa.VARCHAR(), autoincrement=False, nullable=True))
    op.execute("UPDATE goals SET sphere = spheres[1] WHERE array_length(spheres, 1) > 0")
    op.alter_column("goals", "sphere", nullable=False)
    op.drop_column("goals", "spheres")

    op.add_column("projects", sa.Column("sphere", sa.VARCHAR(), autoincrement=False, nullable=True))
    op.execute("UPDATE projects SET sphere = spheres[1] WHERE array_length(spheres, 1) > 0")
    op.drop_column("projects", "spheres")

    op.drop_table("day_reviews")
    op.drop_table("ai_analytics_cache")
