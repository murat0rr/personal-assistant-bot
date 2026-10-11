from src.integrations.telegram_reader import _chat_type_of

# Чистая функция, не трогает TelegramClient (ленивая конструкция в
# get_client() — импорт модуля сам по себе ничего не подключает).


class User:
    pass


class Chat:
    pass


class Channel:
    def __init__(self, broadcast: bool):
        self.broadcast = broadcast


def test_user_entity_is_chat_type_user():
    assert _chat_type_of(User()) == "user"


def test_basic_group_entity_is_chat_type_group():
    assert _chat_type_of(Chat()) == "group"


def test_broadcast_channel_entity_is_chat_type_channel():
    assert _chat_type_of(Channel(broadcast=True)) == "channel"


def test_megagroup_channel_entity_is_chat_type_group():
    # Супергруппы — тоже класс Channel в Telethon, но broadcast=False —
    # для нашей таксономии это "group", не "channel" (см.
    # models/chat_watch.py::WatchedChat.chat_type).
    assert _chat_type_of(Channel(broadcast=False)) == "group"
