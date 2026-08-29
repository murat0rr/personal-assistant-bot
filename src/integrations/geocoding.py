import logging

import httpx

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim требует содержательный User-Agent — иначе банит запросы.
_HEADERS = {"User-Agent": "personal-telegram-assistant (single-user hobby project)"}


async def geocode(place_name: str) -> tuple[float, float] | None:
    """Превратить описание места (адрес, название заведения, район) в
    координаты через Nominatim (OpenStreetMap, бесплатно, без ключа)."""
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            response = await client.get(
                _NOMINATIM_URL,
                params={"q": place_name, "format": "json", "limit": 1},
            )
            response.raise_for_status()
            results = response.json()
    except Exception:
        logger.exception("Не удалось геокодировать место: %r", place_name)
        return None

    if not results:
        return None

    return float(results[0]["lat"]), float(results[0]["lon"])
