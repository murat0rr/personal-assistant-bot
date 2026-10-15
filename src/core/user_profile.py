from datetime import UTC, datetime

from sqlalchemy import select

from src.core.db import async_session
from src.integrations.claude_client import aggregate_user_profile, update_user_profile
from src.models.note import Note
from src.models.task import Task
from src.models.user_profile import UserProfile

# Персональный контекст пользователя (Phase 98) — цикл целиком:
# опросник (handlers/f_profile.py) → aggregate_user_profile один раз →
# затем ежедневная проверка (maybe_update_profile, scheduler/jobs.py::
# _profile_update_job, 6:00 per-user) дописывает профиль по новым
# заметкам/задачам, если есть что дописывать. get_profile_summary —
# единственная точка чтения для трёх потребителей (совет на день,
# генерация задач из целей, предложение задач под проект/цель в Mini
# App) — везде None, если опросник не пройден, мягкая деградация.


async def get_profile_summary(user_id: int) -> str | None:
    async with async_session() as session:
        return await session.scalar(
            select(UserProfile.summary).where(UserProfile.user_id == user_id)
        )


async def save_profile_from_answers(user_id: int, answers: dict[str, str]) -> str:
    """Вызывается один раз по завершении опросника (handlers/f_profile.py)
    — агрегирует ответы в компактный профиль и сохраняет (upsert,
    повторный проход опросника просто перезаписывает — см. причину в
    SPEC.md Phase 98). last_checked_at ставится в "сейчас", чтобы
    ежедневная джоба не восприняла всю историю заметок/задач ДО
    опросника как "новое с прошлой проверки"."""
    answers_text = "\n\n".join(f"{question}\n{answer}" for question, answer in answers.items())
    summary = await aggregate_user_profile(answers_text)
    now = datetime.now(UTC)

    async with async_session() as session:
        profile = await session.get(UserProfile, user_id)
        if profile is None:
            session.add(
                UserProfile(
                    user_id=user_id,
                    summary=summary,
                    onboarding_answers=answers,
                    last_checked_at=now,
                )
            )
        else:
            profile.summary = summary
            profile.onboarding_answers = answers
            profile.last_checked_at = now
        await session.commit()
    return summary


async def maybe_update_profile(user_id: int) -> None:
    """Ежедневная проверка (scheduler/jobs.py::_profile_update_job,
    6:00 per-user) — смотрит на заметки/задачи, появившиеся с прошлой
    проверки, и решает (через Claude), стоит ли что-то вписать в
    профиль. Короткое замыкание: нет профиля вообще (опросник не
    пройден) — выходим сразу; нет новых заметок/задач — тоже выходим,
    не дёргая Claude впустую (джоба крутится для каждого пользователя
    каждый день бесконечно, вызов не бесплатный)."""
    async with async_session() as session:
        profile = await session.get(UserProfile, user_id)
        if profile is None or profile.summary is None:
            return

        since = profile.last_checked_at or profile.updated_at

        new_notes = (
            await session.scalars(
                select(Note.text).where(Note.user_id == user_id, Note.created_at >= since)
            )
        ).all()
        new_tasks = (
            await session.scalars(
                select(Task.title).where(
                    Task.user_id == user_id,
                    Task.created_at >= since,
                    Task.archived.is_(False),
                )
            )
        ).all()

        now = datetime.now(UTC)
        if new_notes or new_tasks:
            updated = await update_user_profile(profile.summary, list(new_notes), list(new_tasks))
            if updated != profile.summary:
                profile.summary = updated
        profile.last_checked_at = now
        await session.commit()
