import calendar
import time
from datetime import date, datetime

from sqlalchemy import select

from src.core.db import async_session
from src.models.recurring_task_rule import RecurringTaskRule
from src.models.task import Task

_DEFAULT_PRIORITY = "средний"


def _is_due(rule: RecurringTaskRule, today: date) -> bool:
    """Чистая функция (тот же паттерн, что f_reminders.py::_is_due) —
    правило "срабатывает" сегодня, если сегодняшняя дата подходит под
    паттерн И на сегодня ещё не материализовано (последняя защита от
    повторного создания при повторном запуске джобы в тот же день)."""
    if rule.last_materialized_date == today:
        return False

    # Период действия (Phase 73, фидбек) — пусто с обеих сторон значит
    # "без ограничений" (де-факто было всегда, до этой фазы полей вообще
    # не было). Проверяется раньше самого паттерна — вне периода
    # неважно, что показывает schedule_kind.
    if rule.period_start is not None and today < rule.period_start:
        return False
    if rule.period_end is not None and today > rule.period_end:
        return False

    value = rule.schedule_value
    kind = rule.schedule_kind

    if kind == "monthly_day":
        day = value.get("day")
        if day == 32:
            last_day = calendar.monthrange(today.year, today.month)[1]
            return today.day == last_day
        return today.day == day
    if kind == "weekly_day":
        return today.weekday() == value.get("weekday")
    # weekly_days (Phase 73, фидбек — несколько дней недели одним
    # правилом: "по будням"/"по выходным"/любой свой набор дней, вместо
    # отдельного правила на каждый день). weekly_day (в единственном
    # числе) остаётся — не переписываем уже существующие правила,
    # только новые создаются через weekly_days.
    if kind == "weekly_days":
        return today.weekday() in (value.get("weekdays") or [])
    if kind == "interval_days":
        anchor = rule.last_materialized_date or rule.created_at.date()
        interval = value.get("interval_days") or 1
        return (today - anchor).days % interval == 0

    return False


async def create_rule(
    user_id: int,
    title: str,
    schedule_kind: str,
    schedule_value: dict,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict:
    async with async_session() as session:
        rule = RecurringTaskRule(
            user_id=user_id,
            title=title,
            schedule_kind=schedule_kind,
            schedule_value=schedule_value,
            period_start=period_start,
            period_end=period_end,
        )
        session.add(rule)
        await session.commit()
    return {"id": rule.id, "title": rule.title}


async def materialize_due_rules(user_id: int, today: date) -> list[str]:
    """Раз в день, для каждого пользователя отдельно (Phase 40 — своя
    джоба на "сегодня" по его часовому поясу, см. scheduler/jobs.py) —
    для каждого правила ЭТОГО пользователя, чей паттерн подходит под
    сегодня и ещё не материализовано на сегодня, создаёт обычную
    Task-строку на сегодняшнюю дату. Дальше это уже просто задача — ни
    утренняя сводка, ни Mini App не нуждаются в отдельной логике под
    повторяющиеся, ровно как и просилось."""
    created_titles: list[str] = []
    async with async_session() as session:
        result = await session.execute(
            select(RecurringTaskRule).where(
                RecurringTaskRule.archived.is_(False), RecurringTaskRule.user_id == user_id
            )
        )
        rules = result.scalars().all()
        due_rules = [r for r in rules if _is_due(r, today)]

        for rule in due_rules:
            task = Task(
                user_id=user_id,
                title=rule.title,
                due_date=datetime.combine(today, datetime.min.time()),
                priority=_DEFAULT_PRIORITY,
                source="recurring",
                sort_order=time.time(),
                sphere=rule.sphere,
                project_id=rule.project_id,
            )
            session.add(task)
            rule.last_materialized_date = today
            created_titles.append(rule.title)

        await session.commit()
    return created_titles


def _serialize(rule: RecurringTaskRule) -> dict:
    """Mini App (Phase 74) не различает weekly_day (легаси, одно число)
    и weekly_days (Phase 73, список) — отдаёт оба единообразно списком
    weekdays, фронтенду незачем знать про историческую разницу."""
    weekdays = None
    day_of_month = None
    interval_days = None
    if rule.schedule_kind == "weekly_days":
        weekdays = rule.schedule_value.get("weekdays") or []
    elif rule.schedule_kind == "weekly_day":
        w = rule.schedule_value.get("weekday")
        weekdays = [w] if w is not None else []
    elif rule.schedule_kind == "monthly_day":
        day_of_month = rule.schedule_value.get("day")
    elif rule.schedule_kind == "interval_days":
        interval_days = rule.schedule_value.get("interval_days")

    return {
        "id": rule.id,
        "title": rule.title,
        "schedule_kind": "weekly_days" if weekdays is not None else rule.schedule_kind,
        "weekdays": weekdays,
        "day_of_month": day_of_month,
        "interval_days": interval_days,
        "period_start": rule.period_start.isoformat() if rule.period_start else None,
        "period_end": rule.period_end.isoformat() if rule.period_end else None,
    }


async def list_rules(user_id: int) -> list[dict]:
    async with async_session() as session:
        result = await session.execute(
            select(RecurringTaskRule).where(
                RecurringTaskRule.archived.is_(False), RecurringTaskRule.user_id == user_id
            )
        )
        rules = result.scalars().all()
    # Сортировка — по created_at, старые первыми (порядок создания, тот
    # же принцип, что и у большинства других списков в приложении —
    # ручного порядка тут никто не просил).
    return [_serialize(r) for r in sorted(rules, key=lambda r: r.created_at)]


async def archive_rule(rule_id: int, user_id: int) -> None:
    """Удаление ВСЕГО правила (Phase 74, фидбек — свайп в списке
    Mini App) — не трогает уже материализованные Task-строки, они
    независимы от правила (см. materialize_due_rules)."""
    async with async_session() as session:
        rule = await session.get(RecurringTaskRule, rule_id)
        if rule is None or rule.user_id != user_id:
            raise ValueError("recurring rule not found")
        rule.archived = True
        await session.commit()
