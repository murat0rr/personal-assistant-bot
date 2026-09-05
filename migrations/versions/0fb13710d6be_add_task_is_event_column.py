"""add task is_event column

Revision ID: 0fb13710d6be
Revises: 8012247589fb
Create Date: 2026-09-05 19:49:30.872617

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0fb13710d6be"
down_revision: str | Sequence[str] | None = "8012247589fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # is_event, не связанные с этой задачей ix_*_user_id (autogenerate
    # предложил их снести — то же уже известное расхождение моделей/схемы,
    # см. миграцию 8012247589fb) — сознательно не трогаем в этой миграции.
    op.add_column(
        "tasks", sa.Column("is_event", sa.Boolean(), server_default="false", nullable=False)
    )
    # Бэкфилл (Phase 66): "событие" раньше было значением priority
    # ("event"), взаимоисключающим с "высокий" — эти строки получают
    # is_event=true и priority возвращается к обычному дефолту
    # "средний" (у события никогда не было отдельного уровня важности,
    # "event" полностью замещал его — "средний" эквивалентен тому, что
    # было). Остальные строки ("низкий"/"средний"/"высокий"/NULL) не
    # трогаются вообще.
    op.execute("UPDATE tasks SET is_event = true, priority = 'средний' WHERE priority = 'event'")


def downgrade() -> None:
    # Лоссово для задач, ставших одновременно "важными" и "событием"
    # после этой миграции — старая схема физически не могла выразить
    # оба флага сразу, priority='event' здесь неизбежно затирает
    # "высокий" у таких строк (ровно то новое сочетание, ради которого
    # миграция и делалась).
    op.execute("UPDATE tasks SET priority = 'event' WHERE is_event = true")
    op.drop_column("tasks", "is_event")
