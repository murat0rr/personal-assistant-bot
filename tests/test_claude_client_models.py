from src.integrations.claude_client import ChatBatchAnalysis, ExtractedTasks, MaybeDescription

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


# ---- ChatBatchAnalysis (Phase 87, наблюдение за чатами) — notes/tasks
# оба required в схеме тула, но валидный исход включает пустые списки
# (безопасный дефолт analyze_chat_batch при отсутствии tool_use тоже
# собирает именно пустые списки, не отсутствующие поля).


def test_chat_batch_analysis_accepts_notes_and_tasks():
    parsed = ChatBatchAnalysis.model_validate(
        {"notes": ["договорились встретиться в пятницу"], "tasks": ["забронировать столик"]}
    )
    assert parsed.notes == ["договорились встретиться в пятницу"]
    assert parsed.tasks == ["забронировать столик"]


def test_chat_batch_analysis_accepts_empty_lists():
    parsed = ChatBatchAnalysis.model_validate({"notes": [], "tasks": []})
    assert parsed.notes == []
    assert parsed.tasks == []
