"""Google Calendar (Phase 64) — только httpx, без google-api-python-client/
google-auth (тот же стиль, что integrations/weather.py: минимум
зависимостей, прямые вызовы REST API)."""

from datetime import datetime
from typing import Any

import httpx

from src.core.config import settings

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API_BASE = "https://www.googleapis.com/calendar/v3"
_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


class GoogleAuthError(Exception):
    """Refresh/access token отозван или просрочен (Google вернул
    invalid_grant) — вызывающая сторона должна считать аккаунт
    отключённым и попросить пользователя подключить заново."""


def build_auth_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": _SCOPE,
        # offline + consent — иначе Google не отдаст refresh_token,
        # если пользователь уже когда-то соглашался этому приложению.
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{_AUTH_URL}?{httpx.QueryParams(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()


async def refresh_access_token(refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code == 400 and response.json().get("error") == "invalid_grant":
            raise GoogleAuthError("refresh_token отозван или просрочен")
        response.raise_for_status()
        return response.json()["access_token"]


async def list_events(
    access_token: str, calendar_id: str, time_min: datetime, time_max: datetime
) -> list[dict[str, Any]]:
    """singleEvents=true — повторяющиеся события разворачиваются в
    отдельные инстансы (не саму RRULE-запись), иначе многолетнее
    "каждый понедельник" никогда бы не подошло к paginated списку с
    границами по времени."""
    events: list[dict[str, Any]] = []
    params: dict[str, Any] = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "maxResults": 250,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            response = await client.get(
                f"{_API_BASE}/calendars/{calendar_id}/events",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            data = response.json()
            events.extend(data.get("items", []))
            next_page = data.get("nextPageToken")
            if not next_page:
                break
            params["pageToken"] = next_page
    return events
