from src.handlers.f12_briefing import build_briefing_text

_TASKS_TEXT = "🌅 Доброе утро! На сегодня активных задач нет."


def test_tasks_only_when_no_weather_no_habits():
    assert build_briefing_text(_TASKS_TEXT, None, []) == _TASKS_TEXT


def test_includes_weather_line():
    text = build_briefing_text(_TASKS_TEXT, "☀️ 18°C, ветер 3 км/ч", [])
    assert _TASKS_TEXT in text
    assert "☀️ 18°C, ветер 3 км/ч" in text


def test_includes_habits():
    habits = [{"name": "спорт", "streak": 5}, {"name": "чтение", "streak": 0}]
    text = build_briefing_text(_TASKS_TEXT, None, habits)
    assert "🔥 Привычки:" in text
    assert "— спорт: 5 дн." in text
    assert "— чтение: 0 дн." in text


def test_all_three_combined():
    habits = [{"name": "спорт", "streak": 5}]
    text = build_briefing_text(_TASKS_TEXT, "🌧 10°C, ветер 12 км/ч", habits)
    assert text.index(_TASKS_TEXT) < text.index("🌧 10°C")
    assert text.index("🌧 10°C") < text.index("🔥 Привычки:")
