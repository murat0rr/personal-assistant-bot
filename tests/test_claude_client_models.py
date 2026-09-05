from src.integrations.claude_client import ExtractedTasks, MaybeDescription

# Модели, не сетевые вызовы — model_validate на синтетическом
# tool_use.input, тот же приём, что использовался бы для проверки схемы
# без реального похода в Claude (сами вызовы в claude_client.py не
# юнит-тестируются нигде в проекте, живая проверка — докером).


def test_extracted_tasks_accepts_null_description():
    parsed = ExtractedTasks.model_validate(
        {
            "tasks": [
                {"title": "купить хлеб", "priority": "средний", "description": None},
            ]
        }
    )
    assert parsed.tasks[0].description is None


def test_extracted_tasks_accepts_filled_description():
    parsed = ExtractedTasks.model_validate(
        {
            "tasks": [
                {
                    "title": "найти реферат по астрономии",
                    "priority": "средний",
                    "description": "Попробуй Википедию для базовых тем.",
                },
            ]
        }
    )
    assert parsed.tasks[0].description == "Попробуй Википедию для базовых тем."


def test_extracted_tasks_description_defaults_to_none_when_omitted():
    # Phase 65 добавила поле как необязательное — старый формат ответа
    # (без description вообще) не должен ломать валидацию.
    parsed = ExtractedTasks.model_validate({"tasks": [{"title": "задача", "priority": "низкий"}]})
    assert parsed.tasks[0].description is None


def test_maybe_description_accepts_null():
    assert MaybeDescription.model_validate({"description": None}).description is None


def test_maybe_description_accepts_text():
    parsed = MaybeDescription.model_validate({"description": "Приходи пораньше и оденься опрятно."})
    assert parsed.description == "Приходи пораньше и оденься опрятно."
