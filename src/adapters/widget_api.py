"""Виджет на главном экране телефона (Scriptable на iOS, Tasker на
Android, 2026-10-25) — read-only: просто показывает задачи на сегодня,
без возможности отмечать выполненными (сознательно урезано — токен
живёт ~год и расходится по конфигам виджетов на телефоне, при утечке
read-only ограничивает ущерб просмотром, а не правкой данных).

Авторизация — свой bearer-токен (core/widget_token.py), не Telegram
initData (внешний скрипт, не Mini App) и не веб-сессионная кука
(отдельный долгоживущий токен, а не 30-дневная веб-сессия — разный
срок жизни и разная claim-схема, чтобы утечка одного не давала
доступа через другой канал)."""

from fastapi import APIRouter, Header, HTTPException

from src.core.user_location import user_today
from src.core.widget_token import verify_widget_token
from src.handlers.f_set_day_task import _load_tasks_for_date

router = APIRouter(prefix="/widget")


def _authorize(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    user_id = verify_widget_token(authorization.removeprefix("Bearer "))
    if user_id is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user_id


@router.get("/today-tasks")
async def today_tasks(authorization: str | None = Header(None)) -> dict:
    user_id = _authorize(authorization)
    today = await user_today(user_id)
    tasks = await _load_tasks_for_date(user_id, today)
    return {
        "date": today.isoformat(),
        "tasks": [{"id": t.id, "title": t.title, "done": t.done} for t in tasks],
    }
