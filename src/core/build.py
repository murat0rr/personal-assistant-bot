from sqlalchemy import select

from src.core.db import async_session
from src.models.build_request import BuildRequest

# Статусы, при которых запрос считается "ещё идёт" — ровно один такой
# может существовать за раз (см. handlers/f_build.py::handle_build_command).
_ACTIVE_STATUSES = ("pending_plan", "awaiting_approval", "approved", "in_progress")


def _serialize(br: BuildRequest) -> dict:
    return {
        "id": br.id,
        "user_id": br.user_id,
        "chat_id": br.chat_id,
        "text": br.text,
        "status": br.status,
        "plan_text": br.plan_text,
        "plan_message_id": br.plan_message_id,
        "result_summary": br.result_summary,
        "commit_sha": br.commit_sha,
        "created_at": br.created_at.isoformat(),
        "updated_at": br.updated_at.isoformat(),
    }


async def get_build(build_id: int) -> dict | None:
    async with async_session() as session:
        br = await session.get(BuildRequest, build_id)
        return _serialize(br) if br else None


async def get_active_build(user_id: int) -> dict | None:
    async with async_session() as session:
        result = await session.execute(
            select(BuildRequest)
            .where(BuildRequest.user_id == user_id, BuildRequest.status.in_(_ACTIVE_STATUSES))
            .order_by(BuildRequest.created_at.desc())
        )
        br = result.scalars().first()
        return _serialize(br) if br else None


async def create_build_request(user_id: int, chat_id: int, text: str) -> dict:
    async with async_session() as session:
        br = BuildRequest(user_id=user_id, chat_id=chat_id, text=text)
        session.add(br)
        await session.commit()
        await session.refresh(br)
        return _serialize(br)


async def append_clarification(build_id: int, extra_text: str) -> dict:
    """ "✏️ Уточнить" — дописывает ответ владельца к исходному запросу и
    возвращает статус в pending_plan, план переделывается заново с учётом
    уточнения (см. f_build.py — та же заметка в документе: цикл
    план->уточнение может повториться несколько раз)."""
    async with async_session() as session:
        br = await session.get(BuildRequest, build_id)
        if br is None:
            raise ValueError("запрос не найден")
        br.text = f"{br.text}\n\nУточнение: {extra_text}"
        br.status = "pending_plan"
        br.plan_text = None
        br.plan_message_id = None
        await session.commit()
        await session.refresh(br)
        return _serialize(br)


async def set_build_status(build_id: int, status: str) -> dict:
    async with async_session() as session:
        br = await session.get(BuildRequest, build_id)
        if br is None:
            raise ValueError("запрос не найден")
        br.status = status
        await session.commit()
        await session.refresh(br)
        return _serialize(br)


async def get_next_pending() -> dict | None:
    """Единственная точка чтения для периодического агента
    (adapters/internal_api.py) — одновременно активен максимум один
    запрос (см. _ACTIVE_STATUSES/handle_build_command), так что тут
    достаточно просто найти самый старый "рабочий" статус."""
    async with async_session() as session:
        result = await session.execute(
            select(BuildRequest)
            .where(BuildRequest.status.in_(("pending_plan", "approved")))
            .order_by(BuildRequest.created_at.asc())
        )
        br = result.scalars().first()
        return _serialize(br) if br else None


async def save_plan(build_id: int, plan_text: str, plan_message_id: int) -> dict:
    async with async_session() as session:
        br = await session.get(BuildRequest, build_id)
        if br is None:
            raise ValueError("запрос не найден")
        br.plan_text = plan_text
        br.plan_message_id = plan_message_id
        br.status = "awaiting_approval"
        await session.commit()
        await session.refresh(br)
        return _serialize(br)


async def finish_build(
    build_id: int, status: str, result_summary: str, commit_sha: str | None
) -> dict:
    async with async_session() as session:
        br = await session.get(BuildRequest, build_id)
        if br is None:
            raise ValueError("запрос не найден")
        br.status = status
        br.result_summary = result_summary
        br.commit_sha = commit_sha
        await session.commit()
        await session.refresh(br)
        return _serialize(br)
