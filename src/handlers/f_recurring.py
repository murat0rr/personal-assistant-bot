import logging

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.core.recurring_tasks import create_rule
from src.core.user_location import user_today
from src.integrations.claude_client import RecurringTaskPlan, parse_recurring_task

logger = logging.getLogger(__name__)


class RecurringClarificationStates(StatesGroup):
    awaiting_answer = State()


_WEEKDAY_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Защита от бесконечного диалога уточнений (Phase 73) — если за
# несколько заходов Claude всё ещё не может собрать план, не тянем
# пользователя по кругу вечно.
_MAX_CLARIFICATION_ROUNDS = 3


def _plan_to_value(plan: RecurringTaskPlan) -> dict:
    if plan.schedule_kind == "monthly_day":
        return {"day": plan.day_of_month}
    if plan.schedule_kind == "weekly_days":
        return {"weekdays": sorted(set(plan.weekdays or []))}
    return {"interval_days": plan.interval_days}


def _describe_schedule(kind: str, value: dict) -> str:
    if kind == "monthly_day":
        day = value.get("day")
        return "каждый месяц в последний день" if day == 32 else f"каждый месяц {day} числа"
    if kind == "weekly_days":
        days = value.get("weekdays") or []
        if days == [0, 1, 2, 3, 4]:
            return "по будням"
        if days == [5, 6]:
            return "по выходным"
        names = [_WEEKDAY_SHORT[d] for d in days if 0 <= d <= 6]
        return f"по дням: {', '.join(names)}" if names else "?"
    return f"раз в {value.get('interval_days')} дн."


def _describe_period(plan: RecurringTaskPlan) -> str:
    # Пусто с обеих сторон — самый частый случай (привычка без заранее
    # известной даты остановки), в сообщении не упоминаем вообще, чтобы
    # не перегружать очевидным "без окончания" каждый раз.
    parts = []
    if plan.period_start:
        parts.append(f"с {plan.period_start.strftime('%d.%m.%Y')}")
    if plan.period_end:
        parts.append(f"до {plan.period_end.strftime('%d.%m.%Y')}")
    return f", {' '.join(parts)}" if parts else ""


async def _run_plan(message: Message, state: FSMContext, conversation: str) -> None:
    """Общая точка входа и для первого сообщения, и для ответа на
    уточняющий вопрос — conversation уже содержит всю историю на этот
    момент (см. handle_recurring_clarification_answer). Либо создаёт
    правило, либо просит ещё одно уточнение и остаётся в состоянии
    ожидания ответа."""
    if not message.from_user:
        return

    try:
        today = await user_today(message.from_user.id)
        plan = await parse_recurring_task(conversation, today)
    except Exception:
        logger.exception("Не удалось разобрать повторяющуюся задачу: %r", conversation)
        await message.answer("Не получилось разобрать, попробуй ещё раз с самого начала.")
        await state.clear()
        return

    if plan.needs_clarification:
        data = await state.get_data()
        rounds = data.get("recurring_rounds", 0) + 1
        if rounds > _MAX_CLARIFICATION_ROUNDS or not plan.clarification_question:
            await message.answer(
                "Не получается разобрать — опиши, пожалуйста, задачу и как часто "
                "её делать одним сообщением с самого начала."
            )
            await state.clear()
            return
        await state.set_state(RecurringClarificationStates.awaiting_answer)
        await state.update_data(
            recurring_conversation=conversation,
            recurring_question=plan.clarification_question,
            recurring_rounds=rounds,
        )
        await message.answer(plan.clarification_question)
        return

    if not plan.schedule_kind or not plan.title:
        await message.answer(
            "Это не похоже на повторяющуюся задачу — опиши, как часто её "
            "делать (например «каждый понедельник разгрести почту», «по "
            "будням зарядка», «5 числа каждого месяца»)."
        )
        await state.clear()
        return

    value = _plan_to_value(plan)
    await create_rule(
        message.from_user.id,
        plan.title,
        plan.schedule_kind,
        value,
        period_start=plan.period_start,
        period_end=plan.period_end,
    )
    schedule_desc = _describe_schedule(plan.schedule_kind, value)
    period_desc = _describe_period(plan)
    await message.answer(
        f"Готово, буду создавать задачу: «{plan.title}» ({schedule_desc}{period_desc})"
    )
    await state.clear()


async def handle_new_recurring_task(message: Message, text: str, state: FSMContext) -> None:
    """Свободный текст ("каждый понедельник разгрести почту") — Claude
    вычленяет паттерн (parse_recurring_task, своя схема — Phase 73,
    раньше переиспользовала parse_reminder), из результата складывается
    RecurringTaskRule. Если данных не хватает (например неясно, в какие
    дни, или упомянуто ограничение по времени без даты) — вместо
    молчаливого угадывания Claude сам просит уточнение, диалог
    продолжается в RecurringClarificationStates. Реальные Task-строки
    появляются только на факт наступившего дня — см.
    scheduler/jobs.py::_materialize_recurring_tasks_job."""
    await _run_plan(message, state, text)


async def handle_recurring_clarification_answer(
    message: Message, text: str, state: FSMContext
) -> None:
    """Ответ на уточняющий вопрос (see handle_new_recurring_task) —
    вся история диалога на этот момент одним текстовым блоком (не
    настоящий многоходовый tool_use/tool_result — см. комментарий у
    parse_recurring_task), чтобы Claude видел полный контекст и не
    просил то, что уже сказали."""
    data = await state.get_data()
    prior = data.get("recurring_conversation", "")
    question = data.get("recurring_question", "")
    conversation = f"{prior}\nАссистент уточнил: {question}\nПользователь ответил: {text}"
    await _run_plan(message, state, conversation)
