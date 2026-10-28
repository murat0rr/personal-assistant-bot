from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core import ack as ack_module
from src.core.ack import ACK_TEXT, reply, working

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def no_real_typing(monkeypatch):
    """ChatActionSender шлёт sendChatAction в настоящий Bot — в тестах
    подменяем на пустой контекстный менеджер."""
    typing = MagicMock()
    typing.return_value.__aenter__ = AsyncMock()
    typing.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(ack_module.ChatActionSender, "typing", typing)
    return typing


def _message() -> MagicMock:
    sent = MagicMock()
    sent.message_id = 1
    sent.delete = AsyncMock()
    sent.answer = AsyncMock()
    message = MagicMock()
    message.chat.id = 7
    message.answer = AsyncMock(return_value=sent)
    return message


async def test_reply_without_working_just_answers():
    message = _message()
    await reply(message, "привет")
    message.answer.assert_awaited_once_with("привет")


async def test_working_sends_ack_and_first_reply_removes_it_and_sends_new(no_real_typing):
    """Фидбек #20 (2026-10-28) — edit_text не шлёт уведомление в
    Telegram, только новое сообщение; первый ответ теперь удаляет
    ack и отвечает новым сообщением, а не правит ack на месте."""
    message = _message()
    sent = message.answer.return_value

    async with working(message):
        await reply(message, "готово")

    assert message.answer.await_args_list[0].args == (ACK_TEXT,)
    sent.delete.assert_awaited_once()
    assert message.answer.await_args_list[-1].args == ("готово",)
    no_real_typing.assert_called_once()


async def test_second_reply_is_also_a_new_message():
    message = _message()
    sent = message.answer.return_value

    async with working(message):
        await reply(message, "первый")
        await reply(message, "второй")

    sent.delete.assert_awaited_once()
    texts = [c.args[0] for c in message.answer.await_args_list]
    assert texts == [ACK_TEXT, "первый", "второй"]


async def test_failed_ack_delete_still_sends_new_message():
    message = _message()
    sent = message.answer.return_value
    sent.delete.side_effect = RuntimeError("message to delete not found")

    async with working(message):
        await reply(message, "ответ")

    sent.delete.assert_awaited_once()
    assert message.answer.await_args_list[-1].args == ("ответ",)


async def test_handler_without_reply_removes_ack_and_sends_new():
    message = _message()
    sent = message.answer.return_value

    async with working(message):
        pass

    sent.delete.assert_awaited_once()
    sent.answer.assert_awaited_once()
    assert "Не смог разобрать" in sent.answer.await_args.args[0]


async def test_exception_removes_ack_sends_new_and_propagates():
    message = _message()
    sent = message.answer.return_value

    with pytest.raises(ValueError):
        async with working(message):
            raise ValueError("boom")

    sent.delete.assert_awaited_once()
    assert "Что-то пошло не так" in sent.answer.await_args.args[0]


async def test_ack_send_failure_does_not_break_handler():
    message = _message()
    message.answer = AsyncMock(side_effect=[RuntimeError("telegram down"), MagicMock()])

    async with working(message):
        await reply(message, "всё равно отвечаю")

    assert message.answer.await_args_list[-1].args == ("всё равно отвечаю",)


async def test_ack_does_not_leak_after_working_exits():
    message = _message()
    async with working(message):
        pass

    message.answer.reset_mock()
    await reply(message, "после")
    message.answer.assert_awaited_once_with("после")
