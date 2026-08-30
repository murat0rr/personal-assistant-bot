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
                "enum": ["once", "monthly_day", "weekly_day", "interval_days", "location"],
                "description": (
                    "'once' — конкретная дата, разово. 'monthly_day' — определённое "
                    "число каждого месяца (day=32 означает 'последний день месяца'). "
                    "'weekly_day' — определённый день недели каждую неделю. "
                    "'interval_days' — каждые N дней начиная с сегодня. "
                    "'location' — упоминание места, а не времени/даты (например "
                    "'когда буду у магазина', 'рядом с домом')."
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
            "place_name": {
                "type": ["string", "null"],
                "description": (
                    "Для 'location' — описание места: адрес, название заведения, "
                    "район, город. Иначе null."
                ),
            },
        },
        "required": ["text", "schedule_kind"],
    },
}


class ReminderPlan(BaseModel):
    text: str
    schedule_kind: Literal["once", "monthly_day", "weekly_day", "interval_days", "location"]
    reminder_date: date | None = None
    day_of_month: int | None = None
    weekday: int | None = None
    interval_days: int | None = None
    place_name: str | None = None


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


_SUGGEST_TEMPLATES_TOOL = {
    "name": "suggest_templates",
    "description": (
        "Предложить новые шаблоны частых задач на основе заголовков задач "
        "пользователя за последнюю неделю."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "0-3 лаконичные формулировки для задач, которые реально "
                    "повторяются за неделю и ещё не покрыты существующими "
                    "шаблонами. Пустой список, если ничего подходящего нет — "
                    "не выдумывай шаблоны только чтобы что-то предложить."
                ),
            },
        },
        "required": ["suggestions"],
    },
}


class TemplateSuggestions(BaseModel):
    suggestions: list[str]


async def suggest_new_templates(recent_titles: list[str], existing_titles: list[str]) -> list[str]:
    """Раз в неделю (см. scheduler/jobs.py::_suggest_templates_job) — по
    заголовкам задач за неделю предлагает 0-3 новых частых формулировки,
    которых ещё нет среди существующих шаблонов."""
    response = await client.messages.create(
        model=settings.claude_model_haiku,
        max_tokens=300,
        system=(
            "Вот заголовки задач пользователя за последнюю неделю и уже "
            "существующие шаблоны частых задач (список готовых формулировок "
            "для быстрого добавления). Предложи новые шаблоны только для "
            "того, что реально повторяется в задачах за неделю и ещё не "
            "покрыто существующими шаблонами — по смыслу, не только по "
            "точному совпадению текста. Не предлагай ничего, если нечего "
            "предложить."
        ),
        tools=[_SUGGEST_TEMPLATES_TOOL],
        tool_choice={"type": "tool", "name": "suggest_templates"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Задачи за неделю:\n{chr(10).join(recent_titles) or '(нет)'}\n\n"
                    f"Существующие шаблоны:\n{chr(10).join(existing_titles) or '(нет)'}"
                ),
            }
        ],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return []
    return TemplateSuggestions.model_validate(tool_use.input).suggestions


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


_GENERATE_TASKS_FROM_GOALS_TOOL = {
    "name": "generate_tasks",
    "description": (
        "Разбить недельные/месячные цели пользователя по сферам жизни на "
        "конкретные выполнимые задачи. Без дат — задачи уходят в инбокс, "
        "пользователь сам расставит их по дням."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Краткая, конкретная задача"},
                        "sphere": {
                            "type": "string",
                            "description": "Сфера, к которой относится задача",
                        },
                        "project_title": {
                            "type": ["string", "null"],
                            "description": (
                                "Название существующего проекта из списка, если задача "
                                "явно относится к одному из них, иначе null."
                            ),
                        },
                    },
                    "required": ["title", "sphere"],
                },
            },
        },
        "required": ["tasks"],
    },
}


class GeneratedGoalTask(BaseModel):
    title: str
    sphere: str
    project_title: str | None = None


class GeneratedGoalTasks(BaseModel):
    tasks: list[GeneratedGoalTask]


async def generate_tasks_from_goals(
    goals: list[dict],
    existing_titles: list[str],
    projects: list[dict],
    period_start: date,
    period_end: date,
) -> list[GeneratedGoalTask]:
    """Раскладывает цели (недельные/месячные, см. handlers/f_goals.py) на
    конкретные выполнимые задачи, без дат — они уходят в инбокс, пользователь
    сам расставляет их по дням. `period_start`/`period_end` — только для
    контекста (масштаб цели), на сами задачи не влияют."""
    goals_text = "\n".join(f"[{g['sphere']}] {g['text']}" for g in goals)
    projects_text = (
        "\n".join(f"- {p['title']}: {p.get('description') or ''}" for p in projects)
        or "(активных проектов нет)"
    )
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=1500,
        system=(
            f"Период цели: с {period_start.isoformat()} по {period_end.isoformat()} "
            "(используй только чтобы понять масштаб — недельная цель ⇒ небольшие "
            "задачи, месячная ⇒ покрупнее). Разложи цели пользователя по сферам "
            "жизни на конкретные, выполнимые задачи. Даты не проставляй — все "
            "задачи уйдут в инбокс, пользователь сам расставит их по дням. Не "
            "дублируй уже существующие задачи (список ниже). Если задача явно "
            "относится к одному из текущих проектов — укажи его точное "
            "название, иначе null."
        ),
        tools=[_GENERATE_TASKS_FROM_GOALS_TOOL],
        tool_choice={"type": "tool", "name": "generate_tasks"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Цели:\n{goals_text}\n\n"
                    f"Уже существующие задачи:\n{chr(10).join(existing_titles) or '(нет)'}\n\n"
                    f"Текущие проекты:\n{projects_text}"
                ),
            }
        ],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return []
    return GeneratedGoalTasks.model_validate(tool_use.input).tasks


_PROPOSE_PROJECTS_TOOL = {
    "name": "propose_projects",
    "description": (
        "Предложить новые проекты на основе месячных целей пользователя, "
        "если какая-то цель складывается в конкретную многошаговую инициативу."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "projects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "sphere": {"type": "string"},
                        "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    },
                    "required": ["title", "sphere", "start_date", "end_date"],
                },
                "description": (
                    "0-3 проекта. Пустой список, если ни одна цель не тянет на "
                    "отдельный проект — не выдумывай проект ради галочки."
                ),
            },
        },
        "required": ["projects"],
    },
}


class ProposedProject(BaseModel):
    title: str
    description: str = ""
    sphere: str
    start_date: date
    end_date: date


class ProposedProjects(BaseModel):
    projects: list[ProposedProject]


async def propose_projects_from_goals(goals: list[dict], today: date) -> list[ProposedProject]:
    """Раз в месяц, после того как заданы месячные цели по всем сферам —
    смотрит, не складывается ли какая-то цель в конкретную многошаговую
    инициативу (см. handlers/f_goals.py), и если да — предлагает Project
    со сроками по контексту цели."""
    goals_text = "\n".join(f"[{g['sphere']}] {g['text']}" for g in goals)
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=1000,
        system=(
            f"Сегодня {today.isoformat()}. Вот месячные цели пользователя по "
            "сферам жизни. Если какая-то цель — это на самом деле крупная "
            "многошаговая инициатива (а не просто повторяющееся намерение), "
            "предложи под неё проект со сроками, разумно вытекающими из "
            "контекста цели (обычно в пределах текущего месяца или чуть "
            "дальше). Не предлагай проект под каждую цель — только там, где "
            "это реально имеет смысл."
        ),
        tools=[_PROPOSE_PROJECTS_TOOL],
        tool_choice={"type": "tool", "name": "propose_projects"},
        messages=[{"role": "user", "content": f"Месячные цели:\n{goals_text}"}],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return []
    return ProposedProjects.model_validate(tool_use.input).projects


_TIDY_TASKS_TOOL = {
    "name": "tidy_tasks",
    "description": (
        "Сделать заголовки задач лаконичнее и понятнее, сохранив исходный "
        "смысл — без выдумывания деталей, которых не было."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Индекс задачи из присланного списка",
                        },
                        "tidied_title": {
                            "type": "string",
                            "description": "Улучшенный заголовок (или тот же, если менять нечего)",
                        },
                        "changed": {
                            "type": "boolean",
                            "description": "true, только если заголовок реально стал лучше",
                        },
                    },
                    "required": ["index", "tidied_title", "changed"],
                },
            },
        },
        "required": ["items"],
    },
}


class TidiedTask(BaseModel):
    index: int
    tidied_title: str
    changed: bool


class TidiedTasks(BaseModel):
    items: list[TidiedTask]


async def tidy_task_titles(titles: list[str]) -> list[TidiedTask]:
    """Ночной разбор инбокса (см. scheduler/jobs.py::_tidy_inbox_job) —
    причёсывает заголовки задач: убирает опечатки, лишние слова, делает
    формулировку понятнее, не трогая смысл. changed=false для заголовков,
    которые и так в порядке — не переписывать ради переписывания."""
    if not titles:
        return []
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    response = await client.messages.create(
        model=settings.claude_model_haiku,
        max_tokens=1500,
        system=(
            "Вот заголовки задач пользователя (нумерованный список). Для "
            "каждой — предложи более лаконичную и понятную формулировку, если "
            "она реально нужна (опечатки, лишние слова, невнятная "
            "формулировка). Не меняй смысл и не добавляй деталей, которых не "
            "было. Если заголовок уже хорош — верни его как есть с "
            "changed=false."
        ),
        tools=[_TIDY_TASKS_TOOL],
        tool_choice={"type": "tool", "name": "tidy_tasks"},
        messages=[{"role": "user", "content": numbered}],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return []
    return TidiedTasks.model_validate(tool_use.input).items


_SUGGEST_TODAY_TOOL = {
    "name": "suggest_today",
    "description": (
        "Выбрать, какие задачи из инбокса желательно сделать сегодня, "
        "с учётом уже имеющейся нагрузки на день."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "id задач из присланного списка инбокса, которые желательно "
                    "сделать сегодня. Пустой список, если день и так плотный, "
                    "или в инбоксе нет ничего срочного/важного — не "
                    "перегружай день ради галочки."
                ),
            },
        },
        "required": ["task_ids"],
    },
}


class TodaySuggestion(BaseModel):
    task_ids: list[int]


async def suggest_tasks_for_today(
    overdue_titles: list[str], today_titles: list[str], inbox_items: list[dict]
) -> list[int]:
    """Утренний совет (см. scheduler/jobs.py::_morning_digest) — смотрит,
    что не сделано со вчера, что уже стоит на сегодня, и что лежит в
    инбоксе, и с учётом графика 5/2 по 8 часов (в будни мало свободного
    времени, в выходные больше) предлагает, что из инбокса имеет смысл
    подтянуть на сегодня. Список пустой, если день и так плотный."""
    if not inbox_items:
        return []
    inbox_text = "\n".join(f"{item['id']}: {item['title']}" for item in inbox_items)
    weekday_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    today = date.today()
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=500,
        system=(
            f"Сегодня {weekday_ru[today.weekday()]}. Пользователь работает по "
            "графику 5/2 (Пн-Пт, полный день) — в будни свободного времени "
            "на личные задачи немного, в выходные заметно больше. Вот что "
            "не сделано со вчера, что уже стоит на сегодня, и что лежит в "
            "инбоксе (без даты). Оцени текущую нагрузку на сегодня и "
            "предложи, какие задачи из инбокса реально стоит добавить на "
            "сегодня — не перегружая день. Если день и так плотный или в "
            "инбоксе нет ничего срочного/важного — пустой список, это "
            "нормальный исход."
        ),
        tools=[_SUGGEST_TODAY_TOOL],
        tool_choice={"type": "tool", "name": "suggest_today"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Не сделано со вчера:\n{chr(10).join(overdue_titles) or '(нет)'}\n\n"
                    f"Уже стоит на сегодня:\n{chr(10).join(today_titles) or '(нет)'}\n\n"
                    f"Инбокс:\n{inbox_text}"
                ),
            }
        ],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return []
    valid_ids = {item["id"] for item in inbox_items}
    return [i for i in TodaySuggestion.model_validate(tool_use.input).task_ids if i in valid_ids]


async def analyze_productivity(spheres: list[dict], month: dict, projects: list[dict]) -> str:
    """Аналитика (Phase 24) — текстовые наблюдения по сферам/месяцу/
    проектам: что хорошо, что плохо. Обычный текстовый ответ, без
    forced tool-use — тут не нужна структура, только читаемый текст."""
    spheres_text = (
        "\n".join(f"{s['sphere']}: {s['count']}" for s in spheres) or "(сферы не проставлены)"
    )
    projects_text = (
        "\n".join(f"- {p['title']}: {p['done_count']}/{p['task_count']}" for p in projects)
        or "(активных проектов нет)"
    )
    total_this_month = sum(month.get("all_counts", []))
    response = await client.messages.create(
        model=settings.claude_model_sonnet,
        max_tokens=600,
        system=(
            "Проанализируй, как у пользователя распределены задачи по сферам "
            "жизни, сколько сделано за месяц, и как продвигаются проекты. "
            "Отметь 2-3 наблюдения: что идёт хорошо, что настораживает "
            "(перекос в одну сферу, забытая сфера, застрявший проект и "
            "т.п.). Коротко (4-6 предложений), по-русски, без воды и без "
            "заголовков-списков — обычный связный текст."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Задачи по сферам:\n{spheres_text}\n\n"
                    f"Выполнено задач в этом месяце: {total_this_month}\n\n"
                    f"Проекты (выполнено/всего задач):\n{projects_text}"
                ),
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text")


_LINK_TASKS_TOOL = {
    "name": "link_tasks",
    "description": "Выбрать, какие из присланных задач реально относятся к проекту/цели.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "id задач, которые реально относятся к проекту/цели по смыслу. "
                    "Пустой список, если ни одна не подходит — не привязывай "
                    "задачи только ради галочки."
                ),
            },
        },
        "required": ["task_ids"],
    },
}


class LinkedTasks(BaseModel):
    task_ids: list[int]


async def find_tasks_for_entity(
    entity_title: str, entity_description: str | None, candidate_tasks: list[dict]
) -> list[int]:
    """ "Проанализировать задачи и добавить в проект/цель" (Phase 26,
    форма создания в Mini App) — среди уже существующих задач без
    привязки (инбокс + будущие) выбирает те, что реально относятся к
    этому проекту/цели по смыслу заголовка. Не создаёт новых задач —
    только привязывает существующие, в отличие от generate_tasks_from_goals."""
    if not candidate_tasks:
        return []
    tasks_text = "\n".join(f"{t['id']}: {t['title']}" for t in candidate_tasks)
    response = await client.messages.create(
        model=settings.claude_model_haiku,
        max_tokens=500,
        system=(
            "Вот название и описание проекта/цели, и список задач пользователя "
            "без привязки (id: заголовок). Выбери id тех задач, что по смыслу "
            "реально относятся к этому проекту/цели. Не выдумывай натянутые "
            "связи — пустой список, если ничего явно не подходит."
        ),
        tools=[_LINK_TASKS_TOOL],
        tool_choice={"type": "tool", "name": "link_tasks"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Проект/цель: {entity_title}\n"
                    f"Описание: {entity_description or '(нет)'}\n\n"
                    f"Задачи:\n{tasks_text}"
                ),
            }
        ],
    )
    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return []
    valid_ids = {t["id"] for t in candidate_tasks}
    return [i for i in LinkedTasks.model_validate(tool_use.input).task_ids if i in valid_ids]
