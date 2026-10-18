import logging
from typing import Literal

from src.core import prompts
from src.core.config import settings
from src.integrations.claude_client import call_with_tool

logger = logging.getLogger(__name__)

Intent = Literal["task", "note", "question", "reminder", "feedback"]

_CLASSIFY_INTENT_TOOL = {
    "name": "classify_intent",
    "description": "Определить тип запроса пользователя.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["task", "note", "question", "reminder", "feedback"],
                "description": (
                    "'task' — что-то сделать/купить (появится в Tasks со сроком и "
                    "приоритетом). 'note' — просто сохранить мысль/информацию без "
                    "действия. 'question' — рецепт, вопрос, выбор, что-то узнать "
                    "или сравнить. 'reminder' — напомнить в будущем по расписанию "
                    "(дата, периодичность). 'feedback' — баг/идея/пожелание ПРО "
                    "САМ ЭТОТ БОТ ('не сохранилась дата', 'сделай тёмную тему', "
                    "'было бы круто если бы...') — не про жизнь пользователя, а "
                    "про приложение, которым он сейчас пользуется."
                ),
            },
        },
        "required": ["intent"],
    },
}


async def classify_intent(text: str) -> Intent:
    """Самый первый шаг обработки любого сообщения (core/orchestrator.py)
    — безопасный дефолт 'task' и при пустом tool_use, и при исключении
    самого вызова (сеть/прокси, см. call_with_tool и TECHDEBT.md про
    CLAUDE_BASE_URL): это первый пункт конвейера создания задачи, и если
    он падает без фоллбэка, сообщение пользователя пропадает молча ещё
    до того, как дошло до handle_task_note."""
    try:
        response = await call_with_tool(
            model=settings.claude_model_haiku,
            max_tokens=50,
            system=prompts.CLASSIFY_INTENT,
            tools=[_CLASSIFY_INTENT_TOOL],
            messages=[{"role": "user", "content": text}],
        )
    except Exception:
        logger.exception("classify_intent: вызов Claude упал, считаю intent='task'")
        return "task"
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return "task"
    return tool_use.input["intent"]
