from datetime import datetime

import pytest

from src.core import tasks_cache
from src.models.task import Task

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _task(**overrides) -> Task:
    defaults = dict(
        id=1,
        title="купить хлеб",
        due_date=None,
        priority="средний",
        done=False,
        sort_order=1.0,
        project_id=None,
        sphere=None,
        description=None,
        is_event=False,
        source="MiniApp",
        recurring_rule_id=None,
        duration_minutes=None,
    )
    defaults.update(overrides)
    return Task(**defaults)


def test_row_roundtrip_without_due_date():
    task = _task()
    row = tasks_cache._to_row(task)
    restored = tasks_cache._from_row(row)
    assert restored.due_date is None
    assert restored.title == task.title
    assert restored.id == task.id


def test_row_roundtrip_with_due_date_and_time():
    task = _task(due_date=datetime(2026, 8, 29, 14, 30), is_event=True)
    row = tasks_cache._to_row(task)
    restored = tasks_cache._from_row(row)
    assert restored.due_date == datetime(2026, 8, 29, 14, 30)
    assert restored.is_event is True


async def test_cache_miss_returns_none():
    assert await tasks_cache.get_cached_tasks(999) is None


async def test_set_then_get_returns_equivalent_tasks():
    tasks = [
        _task(id=1, title="первая"),
        _task(id=2, title="вторая", due_date=datetime(2026, 8, 29)),
    ]
    await tasks_cache.set_cached_tasks(42, tasks)

    cached = await tasks_cache.get_cached_tasks(42)
    assert cached is not None
    assert [t.title for t in cached] == ["первая", "вторая"]
    assert cached[1].due_date == datetime(2026, 8, 29)


async def test_invalidate_clears_cache():
    await tasks_cache.set_cached_tasks(42, [_task()])
    assert await tasks_cache.get_cached_tasks(42) is not None

    await tasks_cache.invalidate_tasks_cache(42)
    assert await tasks_cache.get_cached_tasks(42) is None


async def test_different_users_do_not_share_cache():
    await tasks_cache.set_cached_tasks(1, [_task(id=1, title="у первого")])
    await tasks_cache.set_cached_tasks(2, [_task(id=2, title="у второго")])

    first = await tasks_cache.get_cached_tasks(1)
    second = await tasks_cache.get_cached_tasks(2)
    assert [t.title for t in first] == ["у первого"]
    assert [t.title for t in second] == ["у второго"]
