from src.integrations.weather import _format_weather


def test_clear_sky():
    assert _format_weather(0, 18.4, 3.2) == "☀️ 18°C, ветер 3 км/ч"


def test_rain():
    assert _format_weather(63, 9.6, 12.0) == "🌧 10°C, ветер 12 км/ч"


def test_thunderstorm():
    assert _format_weather(95, 22.0, 7.0) == "⛈ 22°C, ветер 7 км/ч"


def test_unknown_code_falls_back_to_default_emoji():
    assert _format_weather(12345, 5.0, 1.0) == "🌡 5°C, ветер 1 км/ч"


def test_forecast_appended_when_available():
    result = _format_weather(0, 5.0, 10.0, temp_max_c=12.4, temp_min_c=1.6)
    assert result == "☀️ 5°C, ветер 10 км/ч (днём до 12°C, ночью до 2°C)"


def test_forecast_includes_precipitation_when_given():
    result = _format_weather(
        63, 9.6, 12.0, temp_max_c=11.0, temp_min_c=7.0, precipitation_probability=42.0
    )
    assert result == "🌧 10°C, ветер 12 км/ч (днём до 11°C, ночью до 7°C, 42% осадков)"


def test_no_forecast_section_when_max_or_min_missing():
    assert _format_weather(0, 18.4, 3.2, temp_max_c=20.0) == "☀️ 18°C, ветер 3 км/ч"
