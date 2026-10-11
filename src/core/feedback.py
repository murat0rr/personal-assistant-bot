import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from src.core.db import async_session
from src.integrations.claude_client import triage_feedback
from src.models.feedback import Feedback

logger = logging.getLogger(__name__)

# Фоновый триаж не должен блокировать ответ пользователю в боте — тот же
# приём, что у _background_tasks в adapters/api.py (asyncio.create_task
# без сильной ссылки сборщик мусора вправе прервать на полпути).
_background_tasks: set[asyncio.Task] = set()


def _serialize(fb: Feedback) -> dict:
    return {
        "id": fb.id,
        "user_id": fb.user_id,
        "text": fb.text,
        "created_at": fb.created_at.isoformat(),
        "category": fb.category,
        "ai_summary": fb.ai_summary,
        "ai_rationale": fb.ai_rationale,
        "auto_applicable": fb.auto_applicable,
        "status": fb.status,
        "resolution_note": fb.resolution_note,
        "commit_sha": fb.commit_sha,
        "processed_at": fb.processed_at.isoformat() if fb.processed_at else None,
    }


async def create_feedback(user_id: int, text: str) -> dict:
    """Бот только вставляет строку — никакого похода в ИИ синхронно в
    хендлере (см. handlers/f_feedback.py) и никакого доступа к коду или
    файловой системе: это физически не может исполнить то, что написал
    пользователь. Триаж запускается фоном сразу следом, не блокируя ответ."""
    async with async_session() as session:
        fb = Feedback(user_id=user_id, text=text)
        session.add(fb)
        await session.commit()
        await session.refresh(fb)

    task = asyncio.create_task(_triage_background(fb.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return _serialize(fb)


async def _triage_background(feedback_id: int) -> None:
    try:
        async with async_session() as session:
            fb = await session.get(Feedback, feedback_id)
            if fb is None:
                return
            result = await triage_feedback(fb.text)
            fb.category = result.category
            fb.ai_summary = result.summary
            fb.ai_rationale = result.rationale
            fb.auto_applicable = result.auto_applicable
            fb.status = "triaged"
            await session.commit()
    except Exception:
        logger.exception("Не удалось протриажить отзыв %s", feedback_id)


async def list_feedback(
    *, status: str | None = None, auto_applicable: bool | None = None
) -> list[dict]:
    """Единственный читатель — периодический агент через
    adapters/internal_api.py (не Mini App, своего UI у отзывов нет)."""
    async with async_session() as session:
        query = select(Feedback)
        if status is not None:
            query = query.where(Feedback.status == status)
        if auto_applicable is not None:
            query = query.where(Feedback.auto_applicable.is_(auto_applicable))
        query = query.order_by(Feedback.created_at.asc())
        result = await session.execute(query)
        return [_serialize(fb) for fb in result.scalars().all()]


async def update_feedback(
    feedback_id: int,
    *,
    status: str | None = None,
    resolution_note: str | None = None,
    commit_sha: str | None = None,
) -> dict:
    async with async_session() as session:
        fb = await session.get(Feedback, feedback_id)
        if fb is None:
            raise ValueError("отзыв не найден")
        if status is not None:
            fb.status = status
            fb.processed_at = datetime.now(UTC)
        if resolution_note is not None:
            fb.resolution_note = resolution_note
        if commit_sha is not None:
            fb.commit_sha = commit_sha
        await session.commit()
        await session.refresh(fb)
        return _serialize(fb)
