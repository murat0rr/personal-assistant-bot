import logging

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Упрощённая карта WMO weather_code -> эмодзи (открытый справочник Open-Meteo).
_WEATHER_EMOJI = {
    0: "☀️",
    1: "🌤",
    2: "⛅",
    3: "☁️",
    45: "🌫",
    48: "🌫",
    51: "🌦",
    53: "🌦",
    55: "🌦",
    56: "🌧",
    57: "🌧",
    61: "🌧",
    63: "🌧",
    65: "🌧",
    66: "🌧",
    67: "🌧",
    71: "🌨",
    73: "🌨",
    75: "🌨",
    77: "🌨",
    80: "🌦",
    81: "🌧",
    82: "🌧",
    85: "🌨",
    86: "🌨",
    95: "⛈",
    96: "⛈",
    99: "⛈",
}
_DEFAULT_EMOJI = "🌡"


def _format_weather(weather_code: int, temp_c: float, wind_kmh: float) -> str:
    emoji = _WEATHER_EMOJI.get(weather_code, _DEFAULT_EMOJI)
    return f"{emoji} {round(temp_c)}°C, ветер {round(wind_kmh)} км/ч"


async def get_weather_summary() -> str | None:
    if not settings.weather_city:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            geo_response = await client.get(
                _GEOCODE_URL,
                params={"name": settings.weather_city, "count": 1, "language": "ru"},
            )
            geo_response.raise_for_status()
            results = geo_response.json().get("results")
            if not results:
                logger.warning("Не найден город для погоды: %r", settings.weather_city)
                return None

            latitude, longitude = results[0]["latitude"], results[0]["longitude"]
            forecast_response = await client.get(
                _FORECAST_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "timezone": "auto",
                },
            )
            forecast_response.raise_for_status()
            current = forecast_response.json()["current"]
    except Exception:
        logger.exception("Не удалось получить погоду")
        return None

    return _format_weather(
        current["weather_code"], current["temperature_2m"], current["wind_speed_10m"]
    )
