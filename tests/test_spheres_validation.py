import pydantic
import pytest

from src.adapters.api import (
    CreateGoalRequest,
    CreateProjectRequest,
    EditGoalRequest,
    EditProjectRequest,
    _validate_nonempty_spheres,
    _validate_spheres,
)

# Валидация списков сфер (Phase 48, project/goal.spheres) — чистые
# функции, без похода в БД (тот же принцип, что и у остальных тестов
# этого файла — см. test_api.py). Task.sphere (одиночная строка,
# _validate_sphere) не в этом пункте, отдельного теста для неё не было
# и раньше.


def test_validate_spheres_accepts_known_values():
    assert _validate_spheres(["работа", "спорт"]) == ["работа", "спорт"]


def test_validate_spheres_accepts_empty_list():
    # У проекта пустой список — валидное состояние ("без сферы").
    assert _validate_spheres([]) == []


def test_validate_spheres_rejects_unknown_value():
    with pytest.raises(ValueError, match="недопустимая сфера"):
        _validate_spheres(["работа", "не-сфера"])


def test_validate_nonempty_spheres_accepts_known_values():
    assert _validate_nonempty_spheres(["учёба"]) == ["учёба"]


def test_validate_nonempty_spheres_rejects_empty_list():
    # У цели список не может быть пустым.
    with pytest.raises(ValueError, match="хотя бы одна сфера"):
        _validate_nonempty_spheres([])


def test_validate_nonempty_spheres_rejects_unknown_value():
    with pytest.raises(ValueError, match="недопустимая сфера"):
        _validate_nonempty_spheres(["не-сфера"])


# ---- То же самое, но на уровне request-моделей (Annotated-обёртка
# может незаметно сломать проброс None/пустого списка — проверяем и её,
# не только голую функцию-валидатор).


def test_create_project_request_allows_empty_spheres():
    payload = CreateProjectRequest(title="Проект", spheres=[])
    assert payload.spheres == []


def test_create_project_request_rejects_unknown_sphere():
    with pytest.raises(pydantic.ValidationError):
        CreateProjectRequest(title="Проект", spheres=["не-сфера"])


def test_edit_project_request_omitted_spheres_stays_none():
    payload = EditProjectRequest()
    assert payload.spheres is None


def test_create_goal_request_rejects_empty_spheres():
    with pytest.raises(pydantic.ValidationError):
        CreateGoalRequest(spheres=[], tier="weekly", text="Цель")


def test_create_goal_request_accepts_nonempty_spheres():
    payload = CreateGoalRequest(spheres=["спорт", "работа"], tier="weekly", text="Цель")
    assert payload.spheres == ["спорт", "работа"]


def test_edit_goal_request_omitted_spheres_stays_none():
    payload = EditGoalRequest()
    assert payload.spheres is None


def test_edit_goal_request_rejects_explicit_empty_spheres():
    with pytest.raises(pydantic.ValidationError):
        EditGoalRequest(spheres=[])
