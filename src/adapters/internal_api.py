"""Внутренний API для периодического облачного агента (Phase 85,
предложение: https://claude.ai/artifact/8xwZx1gqfuuM2KRKmSrNfA) — НЕ
Telegram Mini App (initData) и НЕ SSH, отдельный секрет в заголовке
(тот же hand-rolled паттерн, что tasker_webhook.py::_verify_secret).
Агент получает доступ ровно к двум таблицам через HTTPS, не к шеллу
сервера — специально минимальная поверхность, см. §5/§8 предложения."""

import secrets

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from src.core.bot_client import get_bot
from src.core.build import finish_build, get_build, get_next_pending, save_plan
from src.core.config import settings
from src.core.feedback import list_feedback, update_feedback

router = APIRouter(prefix="/internal")


def _verify_secret(x_agent_secret: str | None) -> None:
    if not settings.agent_webhook_secret or not x_agent_secret:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not secrets.compare_digest(x_agent_secret, settings.agent_webhook_secret):
        raise HTTPException(status_code=401, detail="unauthorized")


# ---- Обратная связь --------------------------------------------------


@router.get("/feedback")
async def list_feedback_endpoint(
    status: str | None = None,
    auto_applicable: bool | None = None,
    x_agent_secret: str | None = Header(None),
) -> list[dict]:
    _verify_secret(x_agent_secret)
    return await list_feedback(status=status, auto_applicable=auto_applicable)


class UpdateFeedbackRequest(BaseModel):
    status: str | None = None
    resolution_note: str | None = None
    commit_sha: str | None = None


@router.patch("/feedback/{feedback_id}")
async def update_feedback_endpoint(
    feedback_id: int,
    payload: UpdateFeedbackRequest,
    x_agent_secret: str | None = Header(None),
) -> dict:
    _verify_secret(x_agent_secret)
    try:
        return await update_feedback(
            feedback_id,
            status=payload.status,
            resolution_note=payload.resolution_note,
            commit_sha=payload.commit_sha,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="feedback not found") from exc


# ---- /build ------------------------------------------------------------


@router.get("/build/next")
async def get_next_build_endpoint(x_agent_secret: str | None = Header(None)) -> dict | None:
    _verify_secret(x_agent_secret)
    return await get_next_pending()


class BuildPlanRequest(BaseModel):
    plan_text: str


@router.post("/build/{build_id}/plan")
async def send_build_plan_endpoint(
    build_id: int, payload: BuildPlanRequest, x_agent_secret: str | None = Header(None)
) -> dict:
    _verify_secret(x_agent_secret)
    build = await get_build(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="build request not found")
    chat_id = build["chat_id"]

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"build:approve:{build_id}"),
                InlineKeyboardButton(text="✏️ Уточнить", callback_data=f"build:clarify:{build_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"build:reject:{build_id}"),
            ]
        ]
    )
    bot = get_bot()
    sent = await bot.send_message(
        chat_id=chat_id,
        text=f"📋 План по запросу #{build_id}:\n\n{payload.plan_text}",
        reply_markup=keyboard,
    )
    try:
        return await save_plan(build_id, payload.plan_text, sent.message_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="build request not found") from exc


class BuildFinishRequest(BaseModel):
    status: str  # done / needs_input / failed
    summary: str
    commit_sha: str | None = None


_FINISH_PREFIX = {
    "done": "✅ Готово",
    "needs_input": "⏸ Остановился, нужно решение",
    "failed": "⚠️ Не получилось",
}


@router.post("/build/{build_id}/finish")
async def finish_build_endpoint(
    build_id: int, payload: BuildFinishRequest, x_agent_secret: str | None = Header(None)
) -> dict:
    _verify_secret(x_agent_secret)
    build = await get_build(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="build request not found")
    chat_id = build["chat_id"]

    prefix = _FINISH_PREFIX.get(payload.status, payload.status)
    text = f"{prefix} — #{build_id}\n\n{payload.summary}"
    if payload.commit_sha:
        text += f"\n\nКоммит: {payload.commit_sha}"
    bot = get_bot()
    await bot.send_message(chat_id=chat_id, text=text)
    try:
        return await finish_build(build_id, payload.status, payload.summary, payload.commit_sha)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="build request not found") from exc
