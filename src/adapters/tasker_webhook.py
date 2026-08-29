import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from src.core.config import settings
from src.core.db import async_session
from src.models.screen_time import ScreenTime

router = APIRouter(prefix="/webhooks/tasker")


class ScreenTimePayload(BaseModel):
    total_minutes: int
    date: str | None = None


def _verify_secret(x_tasker_secret: str | None) -> None:
    if not settings.tasker_webhook_secret or not x_tasker_secret:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not secrets.compare_digest(x_tasker_secret, settings.tasker_webhook_secret):
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/screen-time")
async def receive_screen_time(
    payload: ScreenTimePayload, x_tasker_secret: str | None = Header(None)
) -> dict[str, str]:
    _verify_secret(x_tasker_secret)

    if payload.date:
        entry_date = datetime.fromisoformat(payload.date).date()
    else:
        # Tasker шлёт итог в конце дня — по умолчанию считаем, что это
        # сегодняшний день по локальной таймзоне.
        entry_date = datetime.now(ZoneInfo(settings.timezone)).date()

    async with async_session() as session:
        existing = await session.get(ScreenTime, entry_date)
        if existing is not None:
            existing.total_minutes = payload.total_minutes
            existing.received_at = datetime.now(ZoneInfo(settings.timezone))
        else:
            session.add(
                ScreenTime(
                    entry_date=entry_date,
                    total_minutes=payload.total_minutes,
                    received_at=datetime.now(ZoneInfo(settings.timezone)),
                )
            )
        await session.commit()

    return {"status": "ok"}
