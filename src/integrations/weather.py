import logging

import httpx

from src.core.config import settings
from src.core.user_location import get_user_location

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


def _format_weather(
    weather_code: int,
    temp_c: float,
    wind_kmh: float,
    temp_max_c: float | None = None,
    temp_min_c: float | None = None,
    precipitation_probability: float | None = None,
) -> str:
    emoji = _WEATHER_EMOJI.get(weather_code, _DEFAULT_EMOJI)
    base = f"{emoji} {round(temp_c)}°C, ветер {round(wind_kmh)} км/ч"
    # Phase 98, фидбек — раньше только "сейчас", без прогноза на день
    # целиком (полезнее для планирования одежды/дел, чем мгновенная
    # температура). Опционально — _format_weather уже тестируется без
    # этих аргументов, старое поведение не меняется, если их не передать.
    if temp_max_c is None or temp_min_c is None:
        return base
    details = f"днём до {round(temp_max_c)}°C, ночью до {round(temp_min_c)}°C"
    if precipitation_probability is not None:
        details += f", {round(precipitation_probability)}% осадков"
    return f"{base} ({details})"


async def _resolve_coordinates(
    client: httpx.AsyncClient, user_id: int
) -> tuple[float, float] | None:
    # Живая геопозиция из /timezone (Phase 39, персонально у каждого с
    # Phase 40) — приоритетнее статичного weather_city из .env: точнее
    # (конкретная точка, не центр города по имени) и не требует лишнего
    # geocoding-запроса на каждый вызов. weather_city — запасной вариант
    # только для владельца (единственное, для чего он вообще задан в
    # .env) — остальные пользователи без /timezone просто не получат
    # погоду в сводке, это ожидаемо, не ошибка.
    location = await get_user_location(user_id)
    if location and location.latitude is not None and location.longitude is not None:
        return location.latitude, location.longitude

    if user_id != settings.telegram_user_id or not settings.weather_city:
        return None

    geo_response = await client.get(
        _GEOCODE_URL,
        params={"name": settings.weather_city, "count": 1, "language": "ru"},
    )
    geo_response.raise_for_status()
    results = geo_response.json().get("results")
    if not results:
        logger.warning("Не найден город для погоды: %r", settings.weather_city)
        return None
    return results[0]["latitude"], results[0]["longitude"]


async def get_weather_summary(user_id: int) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            coords = await _resolve_coordinates(client, user_id)
            if coords is None:
                return None
            latitude, longitude = coords

            forecast_response = await client.get(
                _FORECAST_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    # Phase 98, фидбек — прогноз на день, не только "сейчас"
                    # (один и тот же запрос, не второй вызов API).
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto",
                },
            )
            forecast_response.raise_for_status()
            payload = forecast_response.json()
            current = payload["current"]
            daily = payload.get("daily") or {}
    except Exception:
        logger.exception("Не удалось получить погоду")
        return None

    def _first(key: str) -> float | None:
        values = daily.get(key)
        return values[0] if values else None

    return _format_weather(
        current["weather_code"],
        current["temperature_2m"],
        current["wind_speed_10m"],
        _first("temperature_2m_max"),
        _first("temperature_2m_min"),
        _first("precipitation_probability_max"),
    )
