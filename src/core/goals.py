from datetime import date, timedelta

from src.core import projects as projects_repo


def week_bounds(today: date) -> tuple[date, date]:
    # Цели на "предстоящую неделю" — следующий понедельник (если today
    # уже понедельник, тоже берём следующий, не текущий — формула ниже
    # даёт 7, не 0, для этого случая).
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return monday, monday + timedelta(days=6)


def month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    next_month = start.replace(day=28) + timedelta(days=4)
    end = next_month.replace(day=1) - timedelta(days=1)
    return start, end


def year_bounds(today: date) -> tuple[date, date]:
    return today.replace(month=1, day=1), today.replace(month=12, day=31)


# Тир -> функция границ периода — общая для Телеграм-опроса по
# расписанию (scheduler/jobs.py) и ручного создания цели из Mini App
# (api.py) — период считается сервером по сегодняшней дате, если не
# передан явно (Phase 54: раньше это было единственным способом,
# теперь — только фолбэк, см. create_goal_now). Тиров всего три —
# quarterly/5year убраны целиком (Phase 27, явное решение
# пользователя: три тира и хватит).
GOAL_TIER_BOUNDS = {
    "weekly": week_bounds,
    "monthly": month_bounds,
    "yearly": year_bounds,
}

# Проекты и цели — одна сущность (Phase 54, см. models/project.py::tier
# и core/projects.py). Этот модуль — тонкий адаптер над projects_repo:
# сигнатуры всех публичных функций ниже сохранены ровно такими, какими
# были у самостоятельной Goal-таблицы (плюс необязательные новые
# параметры в конце), поэтому handlers/f_goals.py, core/onboarding.py и
# scheduler/jobs.py не потребовали ни единой правки вызовов — они читают
# только именованные параметры функций (period_start/period_end как
# аргументы, не как ключи словаря) и поля "title"/"spheres" из
# возвращаемых словарей. Переименования на границе: старое Goal.text —
# это Project.title (сериализуется здесь как "title", не "text" — было
# решено выпрямить дублирующую развилку entity.title/entity.text на
# фронтенде заодно). Старые Goal.period_start/period_end сериализуются
# как start_date/end_date, теми же именами, что у Project, — единственный
# реальный потребитель именно ЭТИХ ключей словаря (не параметров с тем же
# именем) — api.py::suggest_goal_tasks_endpoint, который правится вместе
# с этим модулем; f_goals.py/claude_client.py их не читают (проверено).
# Так фронтенд может работать с целью и проектом через одни и те же
# renderEntityRow/projectMeta/isEntityIncomplete — без этого все строки
# целей ошибочно подсвечивались бы как "не дозаполнено" (Phase 54, живая
# проверка в dev-харнессе).


def _serialize(project: dict) -> dict:
    """`project` — уже сериализованный projects_repo._serialize dict
    (не ORM-модель) — здесь только переупаковка под форму, которую
    ожидают потребители цели: id/description/spheres/tier/start_date/
    end_date/title/done/color те же имена, что у проекта (см. комментарий
    выше). task_count/done_count — новые в этом ответе (Phase 54): у
    прежней самостоятельной Goal их не было, задача не имела настоящей
    связи с целью; теперь есть бесплатно, и фронтенд показывает их в
    строке цели тем же способом, что у проекта (см. index.html::projectMeta)."""
    return {
        "id": project["id"],
        "description": project["description"],
        "spheres": project["spheres"],
        "tier": project["tier"],
        "start_date": project["start_date"],
        "end_date": project["end_date"],
        "title": project["title"],
        "done": project["done"],
        "color": project["color"],
        "task_count": project["task_count"],
        "done_count": project["done_count"],
    }


async def create_goal(
    user_id: int,
    spheres: list[str],
    tier: str,
    period_start: date | None,
    period_end: date | None,
    title: str,
    description: str | None = None,
    color: str | None = None,
) -> dict:
    # description/color — необязательные, добавлены в конце (Phase 54) —
    # handlers/f_goals.py зовёт эту функцию позиционно только первыми
    # шестью аргументами, новые параметры туда не долетают и остаются
    # None, старое поведение не меняется.
    project = await projects_repo.create_project(
        user_id, title, description, spheres, period_start, period_end, color=color, tier=tier
    )
    return _serialize(project)


async def create_goal_now(
    user_id: int,
    spheres: list[str],
    tier: str,
    title: str,
    today: date,
    reference_date: date | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    description: str | None = None,
    color: str | None = None,
) -> dict:
    """Ручное создание цели из Mini App (Phase 26) — период считается по
    тиру и опорной дате, ЕСЛИ не передан явно (Phase 54: теперь можно
    задать даты напрямую, как у проекта — это и есть "если не указывать
    даты, то проставятся" из требования). `reference_date` (Phase 28) —
    старый путь, всё ещё поддержан: опорная дата для авто-расчёта."""
    if period_start is None and period_end is None:
        bounds = GOAL_TIER_BOUNDS.get(tier)
        period_start, period_end = bounds(reference_date or today) if bounds else (None, None)
    return await create_goal(
        user_id, spheres, tier, period_start, period_end, title, description, color
    )


async def update_goal(
    goal_id: int,
    user_id: int,
    today: date,
    title: str | None = None,
    spheres: list[str] | None = None,
    tier: str | None = None,
    reference_date: date | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    color: str | None = None,
) -> None:
    """Правка полей цели из карточки Mini App (Phase 28; даты/цвет —
    Phase 54) — все аргументы опциональны, передаётся только то, что
    реально поменялось. Если явно переданы period_start/period_end —
    используются как есть (как у проекта). Иначе, если поменялся тир
    и/или reference_date — период пересчитывается из тира (старое
    поведение, теперь фолбэк, не единственный путь)."""
    if (
        period_start is None
        and period_end is None
        and (tier is not None or reference_date is not None)
    ):
        # Явных новых дат нет, но тир и/или опорная дата поменялись —
        # пересчитываем период из тира (старое поведение, теперь
        # фолбэк). Текущий тир/дата нужны, если передан только один из
        # двух — читаем уже сохранённую сущность одним быстрым запросом.
        current = await projects_repo.get_project(goal_id, user_id)
        new_tier = tier or current["tier"]
        bounds = GOAL_TIER_BOUNDS.get(new_tier)
        ref = reference_date or (
            date.fromisoformat(current["start_date"]) if current["start_date"] else today
        )
        period_start, period_end = bounds(ref) if bounds else (None, None)
        tier = new_tier

    await projects_repo.update_project(
        goal_id,
        user_id,
        title=title,
        spheres=spheres,
        start_date=period_start,
        end_date=period_end,
        tier=tier,
    )
    if color is not None:
        await projects_repo.set_project_color(goal_id, user_id, color)


async def list_goals_for_period(
    user_id: int, tier: str, period_start: date | None, period_end: date | None
) -> list[dict]:
    """Цели конкретного тира за конкретный период (по точному совпадению
    границ — все цели одного захода установки целей делятся ровно одним
    периодом, см. handlers/f_goals.py::start_goal_flow)."""
    entities = await projects_repo.list_by_tier(user_id, tier)
    return [
        _serialize(p)
        for p in entities
        if p["start_date"] == (period_start.isoformat() if period_start else None)
        and p["end_date"] == (period_end.isoformat() if period_end else None)
    ]


async def list_active_goals(user_id: int) -> list[dict]:
    """Все неархивированные цели, любых тиров/периодов — для Mini App
    (Phase 26): переключатель сам группирует по тиру на фронтенде."""
    entities = []
    for tier in GOAL_TIER_BOUNDS:
        entities += await projects_repo.list_by_tier(user_id, tier)
    return [_serialize(p) for p in entities]


async def set_goal_done(goal_id: int, user_id: int, done: bool) -> None:
    await projects_repo.set_project_done(goal_id, user_id, done)


async def archive_goal(goal_id: int, user_id: int) -> None:
    await projects_repo.archive_project(goal_id, user_id)
