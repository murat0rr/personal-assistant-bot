import re
from datetime import UTC, datetime

from sqlalchemy import select

from src.core.db import async_session
from src.integrations.claude_client import generate_note_title, suggest_note_tags
from src.models.note import Note, NoteLink, NoteTag, Tag

# `#тег` — Phase 84 (макет:
# https://claude.ai/code/artifact/163711b9-8bdc-4b0c-bc03-03bb3b7e2354).
# Работает из бота (голос/текст) и из Mini App одинаково — просто текст,
# без специального интерфейса под это в самом сообщении.
_TAG_RE = re.compile(r"#([\wа-яА-ЯёЁ-]{2,})")
# `[[Название заметки]]` — ссылка на другую заметку, тот же принцип.
_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _normalize_tag(name: str) -> str:
    return name.strip().lower()


def _extract_hashtags(text: str) -> set[str]:
    return {_normalize_tag(m) for m in _TAG_RE.findall(text) if m.strip()}


def _extract_link_titles(text: str) -> set[str]:
    return {m.strip() for m in _LINK_RE.findall(text) if m.strip()}


async def _get_or_create_tag(session, user_id: int, name: str) -> Tag:
    result = await session.execute(select(Tag).where(Tag.user_id == user_id, Tag.name == name))
    tag = result.scalar_one_or_none()
    if tag is None:
        tag = Tag(user_id=user_id, name=name, usage_count=1, last_used_at=datetime.now(UTC))
        session.add(tag)
        await session.flush()
    else:
        tag.usage_count += 1
        tag.last_used_at = datetime.now(UTC)
    return tag


async def _sync_tags(session, note: Note, explicit_tags: list[str] | None) -> None:
    """Итоговый набор тегов заметки — объединение явно переданного списка
    (кнопки "частые"/"предложил ИИ" во фронтенде) И того, что нашлось в
    тексте как `#слово` (работает и с бота, где явного списка вообще нет).
    Раз выставленный явным списком минус текст не считается "снятием" —
    если пользователь жмёт ✕ на теге, а в тексте всё ещё стоит `#тег`, тег
    вернётся на следующем сохранении: текст в этом смысле важнее списка,
    ожидаемое поведение, не баг (см. комментарий в models/note.py::NoteTag).
    """
    final = {_normalize_tag(t) for t in (explicit_tags or []) if t.strip()}
    final |= _extract_hashtags(note.text)

    result = await session.execute(
        select(NoteTag.tag_id, Tag.name)
        .join(Tag, Tag.id == NoteTag.tag_id)
        .where(NoteTag.note_id == note.id)
    )
    existing = {name: tag_id for tag_id, name in result.all()}

    to_remove = set(existing) - final
    for name in to_remove:
        await session.execute(
            NoteTag.__table__.delete().where(
                NoteTag.note_id == note.id, NoteTag.tag_id == existing[name]
            )
        )

    to_add = final - set(existing)
    for name in to_add:
        tag = await _get_or_create_tag(session, note.user_id, name)
        session.add(NoteTag(note_id=note.id, tag_id=tag.id))


async def _sync_links(session, note: Note) -> None:
    """Пересчитывает исходящие связи целиком — diff, не инкрементальный
    патч (тот же приём, что у материализации повторяющихся задач в другой
    части проекта). Заметки без совпадения по названию — не хранятся
    вообще, фронтенд сам вычисляет "нерешённые" ссылки сверкой текста со
    списком уже известных заметок (см. правую панель макета)."""
    titles = _extract_link_titles(note.text)
    resolved_ids: set[int] = set()
    if titles:
        result = await session.execute(
            select(Note.id, Note.title).where(
                Note.user_id == note.user_id, Note.id != note.id, Note.title.isnot(None)
            )
        )
        by_title = {title.lower(): note_id for note_id, title in result.all()}
        resolved_ids = {by_title[t.lower()] for t in titles if t.lower() in by_title}

    result = await session.execute(
        select(NoteLink.id, NoteLink.to_note_id).where(NoteLink.from_note_id == note.id)
    )
    existing = {to_id: link_id for link_id, to_id in result.all()}

    for to_id, link_id in existing.items():
        if to_id not in resolved_ids:
            await session.execute(NoteLink.__table__.delete().where(NoteLink.id == link_id))
    for to_id in resolved_ids:
        if to_id not in existing:
            session.add(NoteLink(from_note_id=note.id, to_note_id=to_id))


async def _maybe_generate_title(session, note: Note) -> None:
    """Заголовок оставлен пустым — та же логика "фоном после создания",
    что у задач (MAYBE_GENERATE_TASK_DESCRIPTION), но синхронно: создание
    заметки в Mini App уже показывает шиммер/печатающийся заголовок,
    ждущий именно этот ответ — фоновая джоба с отдельным опросом только
    усложнила бы то, что и так уже вписано в сам запрос создания."""
    if note.title:
        return
    try:
        note.title = await generate_note_title(note.text)
        note.title_is_ai = True
    except Exception:
        # Не смогли — заметка остаётся без названия, не ошибка создания
        # целиком (см. Mini App: покажет "Без названия", как обычно).
        pass


def _serialize(note: Note, tags: list[str], link_ids: list[int]) -> dict:
    return {
        "id": note.id,
        "title": note.title,
        "title_is_ai": note.title_is_ai,
        "text": note.text,
        "sphere": note.sphere,
        "project_id": note.project_id,
        "tags": tags,
        "link_ids": link_ids,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


async def create_note(
    user_id: int,
    text: str,
    *,
    title: str | None = None,
    sphere: str | None = None,
    project_id: int | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Сохраняет заметку. `title=None` — либо с бота (там нет отдельного
    поля заголовка вообще), либо из Mini App с оставленным пустым полем —
    в обоих случаях ИИ подбирает название синхронно, до возврата ответа
    (см. _maybe_generate_title)."""
    async with async_session() as session:
        note = Note(user_id=user_id, text=text, title=title, sphere=sphere, project_id=project_id)
        session.add(note)
        await session.flush()

        await _sync_tags(session, note, tags)
        await _sync_links(session, note)
        await _maybe_generate_title(session, note)

        await session.commit()
        await session.refresh(note)
        return await _load_serialized(session, note)


async def update_note(
    note_id: int,
    user_id: int,
    *,
    title: str | None,
    title_is_ai: bool,
    text: str,
    sphere: str | None,
    project_id: int | None,
    tags: list[str] | None,
) -> dict:
    async with async_session() as session:
        note = await session.get(Note, note_id)
        if note is None or note.user_id != user_id:
            raise ValueError("заметка не найдена")

        note.title = title
        note.title_is_ai = title_is_ai
        note.text = text
        note.sphere = sphere
        note.project_id = project_id

        await _sync_tags(session, note, tags)
        await _sync_links(session, note)

        await session.commit()
        await session.refresh(note)
        return await _load_serialized(session, note)


async def delete_note(note_id: int, user_id: int) -> None:
    async with async_session() as session:
        note = await session.get(Note, note_id)
        if note is None or note.user_id != user_id:
            raise ValueError("заметка не найдена")
        await session.delete(note)
        await session.commit()


async def regenerate_note_title(note_id: int, user_id: int) -> str:
    """Кнопка "🔄 другое название" в заметке — вызвана явным действием,
    всегда пишет что-то новое (тот же принцип, что у
    generate_task_description относительно maybe_generate_task_description)."""
    async with async_session() as session:
        note = await session.get(Note, note_id)
        if note is None or note.user_id != user_id:
            raise ValueError("заметка не найдена")
        note.title = await generate_note_title(note.text)
        note.title_is_ai = True
        await session.commit()
        return note.title


async def suggest_tags_for_note(note_id: int, user_id: int) -> list[str]:
    async with async_session() as session:
        note = await session.get(Note, note_id)
        if note is None or note.user_id != user_id:
            raise ValueError("заметка не найдена")
        current_tags = {
            name
            for (name,) in (
                await session.execute(
                    select(Tag.name)
                    .join(NoteTag, NoteTag.tag_id == Tag.id)
                    .where(NoteTag.note_id == note.id)
                )
            ).all()
        }
        pool = await list_tags(user_id)
        pool_names = [t["name"] for t in pool if t["name"] not in current_tags][:40]
        return await suggest_note_tags(note.text, pool_names, list(current_tags))


async def list_tags(user_id: int) -> list[dict]:
    """Весь пул — фронтенд сам считает "топ-5 частых за последнее время"
    (тот же клиентский фильтр, что в макете) и заполняет выпадающий
    список фильтра; пул одного пользователя невелик, отдельный
    серверный "top N" эндпоинт избыточен."""
    async with async_session() as session:
        result = await session.execute(
            select(Tag).where(Tag.user_id == user_id).order_by(Tag.usage_count.desc())
        )
        return [
            {
                "name": t.name,
                "usage_count": t.usage_count,
                "last_used_at": t.last_used_at.isoformat(),
            }
            for t in result.scalars().all()
        ]


async def list_notes(user_id: int) -> list[dict]:
    async with async_session() as session:
        result = await session.execute(
            select(Note).where(Note.user_id == user_id).order_by(Note.created_at.desc())
        )
        notes = result.scalars().all()
        if not notes:
            return []
        note_ids = [n.id for n in notes]

        tag_rows = await session.execute(
            select(NoteTag.note_id, Tag.name)
            .join(Tag, Tag.id == NoteTag.tag_id)
            .where(NoteTag.note_id.in_(note_ids))
        )
        tags_by_note: dict[int, list[str]] = {}
        for note_id, name in tag_rows.all():
            tags_by_note.setdefault(note_id, []).append(name)

        link_rows = await session.execute(
            select(NoteLink.from_note_id, NoteLink.to_note_id).where(
                NoteLink.from_note_id.in_(note_ids)
            )
        )
        links_by_note: dict[int, list[int]] = {}
        for from_id, to_id in link_rows.all():
            links_by_note.setdefault(from_id, []).append(to_id)

        return [
            _serialize(n, tags_by_note.get(n.id, []), links_by_note.get(n.id, [])) for n in notes
        ]


async def _load_serialized(session, note: Note) -> dict:
    tag_rows = await session.execute(
        select(Tag.name).join(NoteTag, NoteTag.tag_id == Tag.id).where(NoteTag.note_id == note.id)
    )
    tags = [name for (name,) in tag_rows.all()]
    link_rows = await session.execute(
        select(NoteLink.to_note_id).where(NoteLink.from_note_id == note.id)
    )
    link_ids = [to_id for (to_id,) in link_rows.all()]
    return _serialize(note, tags, link_ids)
