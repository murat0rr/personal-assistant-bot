"""projects and goals merged into one entity

Revision ID: 7d586fa9ceee
Revises: e409307aca59
Create Date: 2026-09-01 22:48:56.006471

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7d586fa9ceee"
down_revision: str | Sequence[str] | None = "e409307aca59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Автогенерация заодно предложила снять индексы ix_*_user_id на
# habits/recurring_task_rules/reminders/task_templates/tasks/projects —
# то же расхождение с моделями, не связанное с этой фазой, что уже
# встречалось в Phase 48/50 миграциях. Не включаем сюда — отдельный
# вопрос.


def upgrade() -> None:
    op.add_column("projects", sa.Column("tier", sa.String(), nullable=True))
    # id новых строк — НЕ переносим id старых goals: обе таблицы вели
    # свой независимый autoincrement с 1, значения почти наверняка
    # пересекаются с уже существующими id в projects. Ничто в схеме не
    # ссылается на goals.id (задача была "привязана" к цели только по
    # совпадению сферы, не по FK — см. историю Phase 52/54), так что
    # присвоить новые id безопасно и проще, чем городить сдвиг сиквенса.
    op.execute(
        """
        INSERT INTO projects
            (user_id, title, description, spheres, start_date, end_date,
             archived, done, color, tier, created_at)
        SELECT user_id, text, NULL, spheres, period_start, period_end,
               archived, done, NULL, tier, created_at
        FROM goals
        """
    )
    op.drop_table("goals")


def downgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("spheres", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("done", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("archived", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Тот же приём — новые id для перенесённых строк, не старые
    # projects.id (иначе пересеклись бы с тем, что останется в
    # projects). description/color бывших целей теряются на downgrade
    # (в исходной Goal-таблице этих полей не было вовсе) — ожидаемо для
    # отката, не для нормальной работы.
    op.execute(
        """
        INSERT INTO goals
            (user_id, spheres, tier, period_start, period_end, text, done,
             archived, created_at)
        SELECT user_id, spheres, tier, start_date, end_date, title, done,
               archived, created_at
        FROM projects
        WHERE tier IS NOT NULL
        """
    )
    op.execute("DELETE FROM projects WHERE tier IS NOT NULL")
    op.drop_column("projects", "tier")
