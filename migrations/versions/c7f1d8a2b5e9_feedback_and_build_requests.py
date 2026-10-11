"""feedback and build_requests

Phase 85 — два конвейера для автономных агентов (предложение:
https://claude.ai/artifact/8xwZx1gqfuuM2KRKmSrNfA):
`feedback` — баги/идеи от любых авторизованных пользователей, разбирает
периодический агент через узкий allowlist; `build_requests` — мгновенная
реализация по запросу владельца (`/build`), план -> approve -> полный
фазовый цикл, без allowlist.

Revision ID: c7f1d8a2b5e9
Revises: b3c9e1a7f024
Create Date: 2026-10-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7f1d8a2b5e9"
down_revision: str | Sequence[str] | None = "b3c9e1a7f024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("ai_summary", sa.String(), nullable=True),
        sa.Column("ai_rationale", sa.String(), nullable=True),
        sa.Column("auto_applicable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(), nullable=False, server_default="new"),
        sa.Column("resolution_note", sa.String(), nullable=True),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "build_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="pending_plan"),
        sa.Column("plan_text", sa.String(), nullable=True),
        sa.Column("plan_message_id", sa.Integer(), nullable=True),
        sa.Column("result_summary", sa.String(), nullable=True),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("build_requests")
    op.drop_table("feedback")
