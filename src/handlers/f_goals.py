import logging
import time
from datetime import date

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from src.core.auth import is_authorized
from src.core.db import async_session
from src.core.goals import create_goal, list_goals_for_period
from src.core.projects import create_project, find_project_by_title, list_projects
from src.core.user_location import user_today
from src.integrations.claude_client import generate_tasks_from_goals, propose_projects_from_goals
from src.models.task import Task

logger = logging.getLogger(__name__)

router = Router()

# Та же таксономия, что Task.sphere/Project.sphere/фронтенд Mini App
# (src/adapters/miniapp_static/index.html::SPHERES) — единый список,
# согласованный с пользователем в самом начале этой фазы.
SPHERES = ["учёба", "работа", "спорт", "развитие", "отношения"]

_TIER_LABELS = {
    "weekly": "неделю",
    "monthly": "месяц",
    "yearly": "год",
}
# Только эти тиры автоматически раскладываются на задачи/проекты —
# годовые цели прямо не просили превращать в задачи, только фиксировать
# для будущей аналитики.
_TASK_GENERATING_TIERS = {"weekly", "monthly"}


class GoalStates(StatesGroup):
    picking_sphere = State()
    entering_text = State()


def _sphere_keyboard(done_spheres: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for sphere in SPHERES:
        mark = "✅ " if sphere in done_spheres else ""
        rows.append(
            [InlineKeyboardButton(text=f"{mark}{sphere}", callback_data=f"goal:sphere:{sphere}")]
        )
    rows.append([InlineKeyboardButton(text="Готово", callback_data="goal:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def start_goal_flow(
    bot: Bot,
    state: FSMContext,
    user_id: int,
    tier: str,
    period_start: date | None,
    period_end: date | None,
) -> None:
    await state.update_data(
        tier=tier,
        period_start=period_start.isoformat() if period_start else None,
        period_end=period_end.isoformat() if period_end else None,
        done_spheres=[],
    )
    label = _TIER_LABELS[tier]
    await bot.send_message(
        chat_id=user_id,
        text=f"Пора поставить цели на {label}. Выбери сферу — напишешь цель, я её сохраню.",
        reply_markup=_sphere_keyboard([]),
    )
    await state.set_state(GoalStates.picking_sphere)


@router.callback_query(F.data.startswith("goal:sphere:"))
async def handle_sphere_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if (
        not callback.data
        or not isinstance(callback.message, Message)
        or callback.message.bot is None
    ):
        return
    if await state.get_state() != GoalStates.picking_sphere.state:
        await callback.answer("Это уже неактуально", show_alert=True)
        return

    sphere = callback.data.removeprefix("goal:sphere:")
    await state.update_data(current_sphere=sphere)
    await callback.answer()
    await callback.message.answer(f"Какая цель на этот период по сфере «{sphere}»?")
    await state.set_state(GoalStates.entering_text)


@router.message(GoalStates.entering_text)
async def handle_goal_text(message: Message, state: FSMContext) -> None:
    if (
        not message.from_user
        or not await is_authorized(message.from_user.id)
        or message.bot is None
        or not message.text
    ):
        return

    data = await state.get_data()
    tier = data["tier"]
    sphere = data["current_sphere"]
    period_start = date.fromisoformat(data["period_start"]) if data["period_start"] else None
    period_end = date.fromisoformat(data["period_end"]) if data["period_end"] else None

    # Goal.spheres — список (Phase 48), но этот диалог по-прежнему
    # спрашивает одну сферу за раз (цикл "ещё сфера — или готово" уже
    # даёт тот же результат — несколько целей, каждая со своей сферой);
    # оборачиваем в список из одного элемента, не переделывая сам диалог.
    await create_goal(
        message.from_user.id, [sphere], tier, period_start, period_end, message.text.strip()
    )

    done_spheres = [*data.get("done_spheres", []), sphere]
    await state.update_data(done_spheres=done_spheres)
    await message.answer(
        f"Записал цель по сфере «{sphere}». Ещё сфера — или «Готово».",
        reply_markup=_sphere_keyboard(done_spheres),
    )
    await state.set_state(GoalStates.picking_sphere)


@router.callback_query(F.data == "goal:done")
async def handle_goal_done(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not await is_authorized(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if (
        not callback.data
        or not isinstance(callback.message, Message)
        or callback.message.bot is None
    ):
        return
    if await state.get_state() != GoalStates.picking_sphere.state:
        await callback.answer("Это уже неактуально", show_alert=True)
        return

    data = await state.get_data()
    tier = data["tier"]
    period_start = date.fromisoformat(data["period_start"]) if data["period_start"] else None
    period_end = date.fromisoformat(data["period_end"]) if data["period_end"] else None
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()

    if not data.get("done_spheres"):
        await callback.message.answer("Ни одной цели не задано — в следующий раз.")
        return

    await _finish_tier(callback.message.bot, callback.from_user.id, tier, period_start, period_end)


async def _finish_tier(
    bot: Bot, user_id: int, tier: str, period_start: date | None, period_end: date | None
) -> None:
    goals = await list_goals_for_period(user_id, tier, period_start, period_end)
    if tier not in _TASK_GENERATING_TIERS:
        await bot.send_message(
            chat_id=user_id,
            text=f"Цели на {_TIER_LABELS[tier]} сохранены.",
        )
        return

    # Месячные проекты — СНАЧАЛА, до генерации задач: если по этой же
    # цели предложится новый проект, задачи, сгенерированные следующим
    # шагом, должны иметь шанс сразу привязаться к нему (иначе
    # find_project_by_title никогда не найдёт проект, которого на
    # момент генерации задач ещё не существовало в БД).
    if tier == "monthly":
        await _propose_projects_for_month(bot, user_id, goals)

    async with async_session() as session:
        existing_titles = [
            row[0]
            for row in (
                await session.execute(
                    select(Task.title).where(Task.archived.is_(False), Task.user_id == user_id)
                )
            ).all()
        ]
    active_projects = await list_projects(user_id)

    generated = await generate_tasks_from_goals(
        goals, existing_titles, active_projects, period_start, period_end
    )
    created_titles: list[str] = []
    if generated:
        async with async_session() as session:
            for item in generated:
                project = None
                if item.project_title:
                    project = await find_project_by_title(user_id, item.project_title)
                task = Task(
                    user_id=user_id,
                    title=item.title,
                    due_date=None,
                    priority="средний",
                    source="goal",
                    sort_order=time.time(),
                    sphere=item.sphere,
                    project_id=project.id if project else None,
                )
                session.add(task)
                created_titles.append(item.title)
            await session.commit()

    if created_titles:
        names = "\n".join(f"— {t}" for t in created_titles)
        await bot.send_message(
            chat_id=user_id,
            text=f"Цели на {_TIER_LABELS[tier]} сохранены. Добавил задачи в инбокс:\n{names}",
        )
    else:
        await bot.send_message(
            chat_id=user_id,
            text=f"Цели на {_TIER_LABELS[tier]} сохранены.",
        )


async def _propose_projects_for_month(bot: Bot, user_id: int, goals: list[dict]) -> None:
    today = await user_today(user_id)
    proposals = await propose_projects_from_goals(goals, today)
    if not proposals:
        return
    names = []
    for p in proposals:
        await create_project(
            user_id, p.title, p.description or None, [p.sphere], p.start_date, p.end_date
        )
        names.append(f"— {p.title} ({p.start_date.isoformat()} – {p.end_date.isoformat()})")
    await bot.send_message(
        chat_id=user_id,
        text="По итогам месячных целей создал проекты:\n" + "\n".join(names),
    )
