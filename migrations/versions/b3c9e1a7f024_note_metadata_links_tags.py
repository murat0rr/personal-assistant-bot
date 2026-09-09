"""note metadata, links and tags

Phase 84 — заметки: метаданные (сфера/проект-цель/заголовок) и карта
знаний. Макет: https://claude.ai/code/artifact/163711b9-8bdc-4b0c-bc03-03bb3b7e2354

Добавляет title/title_is_ai/sphere/project_id/updated_at к notes,
новые таблицы note_links (связи `[[Название]]` между заметками),
tags и note_tags (пул тегов пользователя, `#тег` в тексте).

Revision ID: b3c9e1a7f024
Revises: d3f7a9c1e5b8
Create Date: 2026-09-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c9e1a7f024"
down_revision: str | Sequence[str] | None = "d3f7a9c1e5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notes", sa.Column("title", sa.String(), nullable=True))
    op.add_column(
        "notes",
        sa.Column("title_is_ai", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("notes", sa.Column("sphere", sa.String(), nullable=True))
    op.add_column("notes", sa.Column("project_id", sa.Integer(), nullable=True))
    op.add_column(
        "notes",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_foreign_key("fk_notes_project_id", "notes", "projects", ["project_id"], ["id"])

    op.create_table(
        "note_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("from_note_id", sa.Integer(), nullable=False),
        sa.Column("to_note_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["from_note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_note_id", "to_note_id", name="uq_note_link_pair"),
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["authorized_users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
    )

    op.create_table(
        "note_tags",
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("note_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("note_tags")
    op.drop_table("tags")
    op.drop_table("note_links")
    op.drop_constraint("fk_notes_project_id", "notes", type_="foreignkey")
    op.drop_column("notes", "updated_at")
    op.drop_column("notes", "project_id")
    op.drop_column("notes", "sphere")
    op.drop_column("notes", "title_is_ai")
    op.drop_column("notes", "title")
