from src.core import prompts
from src.core.config import settings
from src.integrations.claude_client import client

# Нативный server-side тул web_search_20260209 не поддерживается прокси
# limitdeckai.ru — любой запрос с ним падает 400 "tools[0] requires name and
# input_schema", даже когда поиск не нужен (например, рецепт). Известное и
# принятое ограничение (см. Phase 2 в PLAN.md): отвечаем по знаниям модели,
# без реального веб-поиска. Сам системный промпт — src/core/prompts.py::
# ANSWER_QUESTION (Phase 77, вынесено туда вместе со всеми остальными).


async def answer_question(query: str) -> str:
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=1500,
        system=prompts.ANSWER_QUESTION,
        messages=[{"role": "user", "content": query}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
