from src.core.config import settings
from src.integrations.claude_client import client

_WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 5,
}

_SYSTEM_PROMPT = (
    "Ты помогаешь подобрать товар или услугу по бюджету и критериям "
    "пользователя. Используй веб-поиск, чтобы найти 3-5 актуальных "
    "вариантов. Для каждого укажи название, примерную цену и ссылку. "
    "Отвечай кратко, списком, на русском."
)


async def research_options(query: str) -> str:
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=1500,
        system=_SYSTEM_PROMPT,
        tools=[_WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": query}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
