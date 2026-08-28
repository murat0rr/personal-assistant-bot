from datetime import date
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from src.core.config import settings

_EXTRACT_TASK_TOOL = {
    "name": "extract_task",
    "description": "Извлечь структурированные поля задачи из текста сообщения пользователя.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Краткое название задачи",
            },
            "due_date": {
                "type": ["string", "null"],
                "description": "Срок в формате YYYY-MM-DD, или null, если в сообщении не указан",
            },
            "priority": {
                "type": "string",
                "enum": ["низкий", "средний", "высокий"],
                "description": "Приоритет; если явно не указан в сообщении — 'средний'",
            },
        },
        "required": ["title", "priority"],
    },
}

client = AsyncAnthropic(
    api_key=settings.claude_api_key,
    base_url=settings.claude_base_url or None,
)


class TaskFields(BaseModel):
    title: str
    due_date: date | None = None
    priority: Literal["низкий", "средний", "высокий"]


async def extract_task_fields(text: str, today: date) -> TaskFields:
    response = await client.messages.create(
        model=settings.claude_model_haiku,
        max_tokens=300,
        system=(
            f"Сегодняшняя дата: {today.isoformat()}. Извлеки из сообщения "
            "пользователя задачу: название, срок (переведи относительные даты "
            "вроде 'завтра'/'послезавтра' в конкретную дату YYYY-MM-DD) и приоритет."
        ),
        tools=[_EXTRACT_TASK_TOOL],
        tool_choice={"type": "tool", "name": "extract_task"},
        messages=[{"role": "user", "content": text}],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        raise ValueError(f"Claude не вернул структурированный ответ на текст: {text!r}")
    return TaskFields.model_validate(tool_use.input)


async def summarize_diary(answers_text: str) -> str:
    response = await client.messages.create(
        model=settings.claude_model_haiku,
        max_tokens=300,
        system=(
            "Кратко (2-3 предложения) обобщи дневниковую запись пользователя "
            "за день. Дружелюбный тон, на русском, без воды."
        ),
        messages=[{"role": "user", "content": answers_text}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
