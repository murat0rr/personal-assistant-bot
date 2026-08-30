import logging

import httpx

logger = logging.getLogger(__name__)

_NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Nominatim требует содержательный User-Agent — иначе банит запросы.
_HEADERS = {"User-Agent": "personal-telegram-assistant (single-user hobby project)"}


async def geocode(place_name: str) -> tuple[float, float] | None:
    """Превратить описание места (адрес, название заведения, район) в
    координаты через Nominatim (OpenStreetMap, бесплатно, без ключа)."""
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            response = await client.get(
                _NOMINATIM_SEARCH_URL,
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


async def reverse_geocode_label(lat: float, lon: float) -> str | None:
    """Координаты -> человекочитаемая подпись ("Санкт-Петербург, Россия")
    через Nominatim (Phase 39, команда /timezone) — только для
    подтверждающего сообщения пользователю, ни на что в логике не влияет."""
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            response = await client.get(
                _NOMINATIM_REVERSE_URL,
                params={"lat": lat, "lon": lon, "format": "json", "zoom": 10},
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        logger.exception("Не удалось определить название места: %s, %s", lat, lon)
        return None

    address = data.get("address", {})
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("state")
    )
    country = address.get("country")
    if city and country:
        return f"{city}, {country}"
    return city or country or data.get("display_name")


async def resolve_timezone(lat: float, lon: float) -> str | None:
    """Координаты -> IANA-имя часового пояса ("Europe/Moscow") через
    Open-Meteo (тот же провайдер, что уже используется для погоды,
    forecast-эндпоинт с timezone=auto сам резолвит зону по координатам —
    не нужна ни отдельная библиотека, ни второй внешний сервис)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                _FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m",
                    "timezone": "auto",
                },
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        logger.exception("Не удалось определить часовой пояс: %s, %s", lat, lon)
        return None

    return data.get("timezone")
