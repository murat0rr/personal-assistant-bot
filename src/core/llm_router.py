from typing import Literal

from src.core.config import settings
from src.integrations.claude_client import client

Intent = Literal["task", "note", "question", "reminder"]

_CLASSIFY_INTENT_TOOL = {
    "name": "classify_intent",
    "description": "Определить тип запроса пользователя.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["task", "note", "question", "reminder"],
                "description": (
                    "'task' — что-то сделать/купить (появится в Tasks со сроком и "
                    "приоритетом). 'note' — просто сохранить мысль/информацию без "
                    "действия. 'question' — рецепт, вопрос, выбор, что-то узнать "
                    "или сравнить. 'reminder' — напомнить в будущем по расписанию "
                    "(дата, периодичность)."
                ),
            },
        },
        "required": ["intent"],
    },
}


async def classify_intent(text: str) -> Intent:
    response = await client.messages.create(
        model=settings.claude_model_haiku,
        max_tokens=50,
        system="Классифицируй запрос пользователя по одному из сценариев.",
        tools=[_CLASSIFY_INTENT_TOOL],
        tool_choice={"type": "tool", "name": "classify_intent"},
        messages=[{"role": "user", "content": text}],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return "task"
    return tool_use.input["intent"]
