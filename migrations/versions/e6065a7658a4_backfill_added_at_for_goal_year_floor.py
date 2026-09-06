"""backfill added_at for goal year floor

Revision ID: e6065a7658a4
Revises: ff2ba2c15e7b
Create Date: 2026-09-06 00:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy import DateTime

# revision identifiers, used by Alembic.
revision: str = "e6065a7658a4"
down_revision: str | Sequence[str] | None = "ff2ba2c15e7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Только данные, схема не меняется (Phase 68, фидбек: свайп периодов у
# годовых целей не должен пускать пользователя дальше назад, чем год его
# регистрации). У уже существующих пользователей added_at может быть
# заметно раньше 2026 (реальная дата авторизации в боте) — по решению
# пользователя ("added_at + бэкфилл 2026") эффективный "год регистрации"
# для ГОДОВЫХ целей у существующих пользователей принудительно
# становится 2026, а не их настоящий added_at. added_at нигде в
# остальном коде не читается (только пишется при авторизации/создании
# защитной строки-фолбэка — grep подтверждён на момент этой миграции),
# так что переопределение безопасно. Для новых пользователей после этой
# миграции added_at продолжит отражать реальную дату — goal_year_floor
# читает его напрямую, без всякого бэкфилла.
_FLOOR = datetime(2026, 1, 1, tzinfo=UTC)


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE authorized_users SET added_at = :floor WHERE added_at < :floor").bindparams(
            sa.bindparam("floor", value=_FLOOR, type_=DateTime(timezone=True))
        )
    )


def downgrade() -> None:
    # Однонаправленный бэкфилл — реальные исторические added_at ниже
    # 2026 не восстановимы (перезаписаны выше), даунгрейд намеренно
    # ничего не делает.
    pass
