from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class Note(Base):
    """Заметки (Phase 62) — раньше жили целиком в Notion (см.
    handlers/f_notes.py), теперь в Postgres. Простой список записей
    (не одна строка на пользователя, как у DayReview) — заметок за
    день может быть сколько угодно, тот же принцип, что у Reminder.

    Phase 84 — метаданные и карта знаний (макет:
    https://claude.ai/code/artifact/163711b9-8bdc-4b0c-bc03-03bb3b7e2354):
    title/title_is_ai — своё название или придуманное ИИ (см.
    integrations/claude_client.py::generate_note_title); sphere — та же
    таксономия и то же "одно значение", что у Task.sphere (не список,
    как у Project.spheres — заметка обычно про одно); project_id —
    привязка к проекту ИЛИ цели, это одна и та же сущность (см.
    models/project.py::Project.tier). Связи между заметками — NoteLink
    ниже, теги — Tag/NoteTag ниже."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Многопользовательность (Phase 40) — см. Task.user_id. Заметки
    # сейчас доступны только владельцу (см. handlers/f_notes.py,
    # adapters/api.py::_NOT_READY_FOR_OTHERS), но поле сразу общее —
    # тот же принцип, что у остальных моделей.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    # True — заголовок сгенерирован ИИ (пометка ✨ во фронтенде, доступна
    # кнопка "перегенерировать"). Снимается, как только пользователь сам
    # правит поле title — см. core/notes.py::update_note.
    title_is_ai: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    text: Mapped[str] = mapped_column(String)
    sphere: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NoteLink(Base):
    """Связь `[[Название заметки]]` внутри текста (Phase 84) — направленное
    ребро, from → to. Пересчитывается целиком (delete всех исходящих у
    заметки → insert актуальных) при каждом сохранении текста, см.
    core/notes.py::_sync_links — тот же diff-приём, что у материализации
    повторяющихся задач в другой части проекта, не инкрементальный патч."""

    __tablename__ = "note_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_note_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    to_note_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("from_note_id", "to_note_id", name="uq_note_link_pair"),)


class Tag(Base):
    """Пул тегов пользователя (Phase 84) — один тег может стоять на многих
    заметках (NoteTag ниже). usage_count/last_used_at считаются на каждое
    прикрепление (create_note/update_note), не декрементируются при
    отвязывании/удалении заметки — сознательное упрощение, пул
    "популярности" растёт монотонно, см. core/notes.py."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    # Нормализовано (нижний регистр) до записи — см. core/notes.py::_normalize_tag.
    name: Mapped[str] = mapped_column(String, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)


class NoteTag(Base):
    """Заметка↔тег (Phase 84), составной PK — обычная junction-таблица,
    без своего id. Тег — не только то, что буквально набрано `#словом` в
    тексте: "частые теги"/предложения ИИ во фронтенде добавляют сюда
    напрямую, текст при этом не трогается (см. core/notes.py::update_note
    — итоговый набор тегов всегда объединение явного списка И того, что
    нашлось в тексте, не наоборот)."""

    __tablename__ = "note_tags"

    note_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
