from src.handlers.f1_task_note import _fallback_task_fields

# Табличный фолбек без ИИ (фидбек, 2026-10-18) — чистая функция, тот же
# принцип, что у _chat_tag/_is_quiet_hour в других тестах этого проекта.


def test_fallback_uses_whole_text_as_title():
    fields = _fallback_task_fields("купить хлеб и позвонить маме")
    assert fields.title == "купить хлеб и позвонить маме"
    assert fields.due_date is None
    assert fields.priority == "средний"
    assert fields.sphere is None
    assert fields.description is None


def test_fallback_strips_whitespace():
    fields = _fallback_task_fields("  текст с пробелами  \n")
    assert fields.title == "текст с пробелами"


def test_fallback_handles_empty_text():
    fields = _fallback_task_fields("   ")
    assert fields.title == "Задача"
