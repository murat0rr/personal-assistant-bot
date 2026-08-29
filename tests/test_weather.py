from src.integrations.weather import _format_weather


def test_clear_sky():
    assert _format_weather(0, 18.4, 3.2) == "☀️ 18°C, ветер 3 км/ч"


def test_rain():
    assert _format_weather(63, 9.6, 12.0) == "🌧 10°C, ветер 12 км/ч"


def test_thunderstorm():
    assert _format_weather(95, 22.0, 7.0) == "⛈ 22°C, ветер 7 км/ч"


def test_unknown_code_falls_back_to_default_emoji():
    assert _format_weather(12345, 5.0, 1.0) == "🌡 5°C, ветер 1 км/ч"
