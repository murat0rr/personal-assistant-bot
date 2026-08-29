from src.core.config import settings
from src.integrations.claude_client import client

# Нативный server-side тул web_search_20260209 не поддерживается прокси
# limitdeckai.ru — любой запрос с ним падает 400 "tools[0] requires name and
# input_schema", даже когда поиск не нужен (например, рецепт). Известное и
# принятое ограничение (см. Phase 2 в PLAN.md): отвечаем по знаниям модели,
# без реального веб-поиска.
_SYSTEM_PROMPT = (
    "Ты — полезный ассистент. Отвечай на вопросы пользователя: рецепты, "
    "учебные вопросы, выбор между вариантами, подбор товаров/услуг по "
    "бюджету и т.п. Веб-поиска у тебя нет — если для точного ответа нужны "
    "самые свежие данные (актуальные цены, наличие), предупреди об этом "
    "коротко и ответь по своим знаниям с оговоркой, что данные могут быть "
    "не самыми свежими. Отвечай кратко и по делу, на русском."
)


async def answer_question(query: str) -> str:
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=1500,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": query}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
