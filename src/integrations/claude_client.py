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


_PARSE_REMINDER_TOOL = {
    "name": "parse_reminder",
    "description": (
        "Разобрать напоминание, описанное пользователем на естественном языке, "
        "в структурированное расписание."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "О чём напомнить — краткая формулировка",
            },
            "schedule_kind": {
                "type": "string",
                "enum": ["once", "monthly_day", "weekly_day", "interval_days"],
                "description": (
                    "'once' — конкретная дата, разово. 'monthly_day' — определённое "
                    "число каждого месяца (day=32 означает 'последний день месяца'). "
                    "'weekly_day' — определённый день недели каждую неделю. "
                    "'interval_days' — каждые N дней начиная с сегодня."
                ),
            },
            "reminder_date": {
                "type": ["string", "null"],
                "description": "Для 'once' — дата в формате YYYY-MM-DD, иначе null",
            },
            "day_of_month": {
                "type": ["integer", "null"],
                "description": "Для 'monthly_day' — число 1-31, или 32 для последнего дня месяца",
            },
            "weekday": {
                "type": ["integer", "null"],
                "description": "Для 'weekly_day' — 0=понедельник ... 6=воскресенье",
            },
            "interval_days": {
                "type": ["integer", "null"],
                "description": "Для 'interval_days' — раз в сколько дней",
            },
        },
        "required": ["text", "schedule_kind"],
    },
}


class ReminderPlan(BaseModel):
    text: str
    schedule_kind: Literal["once", "monthly_day", "weekly_day", "interval_days"]
    reminder_date: date | None = None
    day_of_month: int | None = None
    weekday: int | None = None
    interval_days: int | None = None


async def parse_reminder(text: str, today: date) -> ReminderPlan:
    response = await client.messages.create(
        model=settings.claude_model_haiku,
        max_tokens=300,
        system=(
            f"Сегодняшняя дата: {today.isoformat()}. Разбери напоминание "
            "пользователя в структурированное расписание."
        ),
        tools=[_PARSE_REMINDER_TOOL],
        tool_choice={"type": "tool", "name": "parse_reminder"},
        messages=[{"role": "user", "content": text}],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        raise ValueError(f"Claude не вернул структурированный ответ на текст: {text!r}")
    return ReminderPlan.model_validate(tool_use.input)


async def summarize_finance_csv(csv_text: str) -> str:
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=1500,
        system=(
            "Тебе присылают CSV-выписку по банковской карте (формат и "
            "названия колонок могут отличаться — определи их сама по "
            "содержимому, включая колонку с суммой и категорией/описанием "
            "операции). Посчитай общую сумму трат, разбивку по категориям "
            "(топ-5), и отметь 1-2 необычно крупные операции, если такие "
            "есть. Игнорируй пополнения и переводы самому себе, если они "
            "отличимы от трат. Ответь компактно, на русском, с эмодзи по "
            "категориям."
        ),
        messages=[{"role": "user", "content": csv_text}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


_ANSWER_QUESTION_TOOL = {
    "name": "answer_question",
    "description": (
        "Ответить на вопрос пользователя (рецепт, учебный вопрос, разбор "
        "домашнего задания по фото/PDF, выбор между вариантами, подбор по "
        "бюджету и т.п.) и приложить файл, если он реально полезен."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reply_text": {
                "type": "string",
                "description": (
                    "Основной ответ, компактно, на русском — не дублируй в "
                    "него содержимое приложенного файла, если он есть."
                ),
            },
            "attachment": {
                "type": ["object", "null"],
                "description": (
                    "Файл-приложение (план подготовки, конспект, "
                    "сравнительная таблица) — только если он реально "
                    "полезен, иначе null."
                ),
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла с расширением .md или .txt",
                    },
                    "content": {
                        "type": "string",
                        "description": "Полное содержимое файла",
                    },
                },
            },
        },
        "required": ["reply_text"],
    },
}


class QuestionAttachment(BaseModel):
    filename: str
    content: str


class QuestionAnswer(BaseModel):
    reply_text: str
    attachment: QuestionAttachment | None = None


async def answer_question_rich(content_blocks: list[dict]) -> QuestionAnswer:
    """Мультимодальный ответ на вопрос (текст/голос/фото/PDF, см. kнопку
    "Вопрос") — в отличие от простого answer_question в web_search.py,
    здесь forced tool-use, чтобы модель сама решала, нужен ли файл-приложение."""
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=4096,
        system=(
            "Ты отвечаешь на вопросы пользователя: рецепты, учебные "
            "вопросы, разбор домашних заданий (в том числе по фото или "
            "PDF), выбор между вариантами, подбор товаров/услуг по "
            "бюджету. Веб-поиска у тебя нет — для вопросов, требующих "
            "самых свежих данных, отвечай по знаниям с оговоркой, что они "
            "могут быть не самыми актуальными. Если это домашнее задание — "
            "дай пошаговый план решения/подготовки и укажи, какие темы "
            "стоит повторить."
        ),
        tools=[_ANSWER_QUESTION_TOOL],
        tool_choice={"type": "tool", "name": "answer_question"},
        messages=[{"role": "user", "content": content_blocks}],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        raise ValueError("Claude не вернул структурированный ответ на вопрос")
    return QuestionAnswer.model_validate(tool_use.input)


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
