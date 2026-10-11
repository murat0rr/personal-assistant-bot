"""db indexes for frequent queries

Только CREATE INDEX, без изменения данных и без блокирующих ALTER.
Синхронизация моделей с уже существующими в БД `ix_*_user_id`
(Phase 40, physически созданы `a7c3e9f1b2d4`, но не отражены в моделях —
дрифт, упомянутый в комментариях Phase 48/84) сюда не входит: там нечего
создавать, autogenerate это уже не предлагает.

- `tasks`: составной (user_id, archived, due_date) — дайджест/таймлайн
  дня/аналитика/календарь (`core/tasks.py`); частичный
  (user_id, google_event_id) где google_event_id не NULL — поиск задачи
  по событию календаря (`core/google_calendar_sync.py`); project_id и
  recurring_rule_id — FK (join/удаление).
- `notes`: (user_id, created_at) — лента заметок (`core/notes.py`);
  project_id — FK.
- `note_links.to_note_id` — обратные связи (прямое направление уже
  покрыто уникальным индексом пары).
- `note_tags.tag_id` — обратный поиск "заметки по тегу" (прямое уже
  покрыто составным PK (note_id, tag_id)).
- `feedback`: (status, created_at) — выборка агента по статусу
  (`core/feedback.py`); user_id — FK.
- `build_requests`: (user_id, status, created_at) — активный запрос
  владельца (`core/build.py::get_active_request`); (status, created_at)
  — следующий в очереди (`core/build.py::get_next_request`).

Revision ID: b8ab5e137d31
Revises: c7f1d8a2b5e9
Create Date: 2026-10-11 03:13:15.720738

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8ab5e137d31"
down_revision: str | Sequence[str] | None = "c7f1d8a2b5e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_tasks_user_id_archived_due_date", "tasks", ["user_id", "archived", "due_date"]
    )
    op.create_index(
        "ix_tasks_user_id_google_event_id",
        "tasks",
        ["user_id", "google_event_id"],
        postgresql_where=sa.text("google_event_id IS NOT NULL"),
    )
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"])
    op.create_index(op.f("ix_tasks_recurring_rule_id"), "tasks", ["recurring_rule_id"])
    op.create_index(
        op.f("ix_recurring_task_rules_project_id"), "recurring_task_rules", ["project_id"]
    )
    op.create_index("ix_notes_user_id_created_at", "notes", ["user_id", "created_at"])
    op.create_index(op.f("ix_notes_project_id"), "notes", ["project_id"])
    op.create_index(op.f("ix_note_links_to_note_id"), "note_links", ["to_note_id"])
    op.create_index(op.f("ix_note_tags_tag_id"), "note_tags", ["tag_id"])
    op.create_index("ix_feedback_status_created_at", "feedback", ["status", "created_at"])
    op.create_index(op.f("ix_feedback_user_id"), "feedback", ["user_id"])
    op.create_index(
        "ix_build_requests_user_id_status_created_at",
        "build_requests",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_build_requests_status_created_at", "build_requests", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_build_requests_status_created_at", table_name="build_requests")
    op.drop_index("ix_build_requests_user_id_status_created_at", table_name="build_requests")
    op.drop_index(op.f("ix_feedback_user_id"), table_name="feedback")
    op.drop_index("ix_feedback_status_created_at", table_name="feedback")
    op.drop_index(op.f("ix_note_tags_tag_id"), table_name="note_tags")
    op.drop_index(op.f("ix_note_links_to_note_id"), table_name="note_links")
    op.drop_index(op.f("ix_notes_project_id"), table_name="notes")
    op.drop_index("ix_notes_user_id_created_at", table_name="notes")
    op.drop_index(op.f("ix_recurring_task_rules_project_id"), table_name="recurring_task_rules")
    op.drop_index(op.f("ix_tasks_recurring_rule_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_index(
        "ix_tasks_user_id_google_event_id",
        table_name="tasks",
        postgresql_where=sa.text("google_event_id IS NOT NULL"),
    )
    op.drop_index("ix_tasks_user_id_archived_due_date", table_name="tasks")
