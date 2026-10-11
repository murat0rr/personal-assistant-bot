from src.core.chat_watch import _chat_tag, _display_name

# Чистые функции без похода в БД/Claude/Telethon — тот же принцип, что
# у _is_quiet_hour/_should_send_nudge в test_task_nag.py. CRUD/батчинг
# core/chat_watch.py трогают реальную Postgres (async_session) и живую
# MTProto-сессию, которых здесь нет — это покрывается живой проверкой
# докером (см. SPEC.md, раздел Phase 87), не этим файлом.


# ---- _chat_tag — slugify заголовка чата под тег (Phase 87) --------------


def test_chat_tag_lowercases_and_joins_with_dash():
    assert _chat_tag("Рабочий Чат") == "рабочий-чат"


def test_chat_tag_strips_punctuation():
    assert _chat_tag("Проект №1 (важное!)") == "проект-1-важное"


def test_chat_tag_falls_back_to_chat_when_empty():
    assert _chat_tag("...") == "chat"


def test_chat_tag_handles_single_word():
    assert _chat_tag("Семья") == "семья"


# ---- _display_name — минимальное хранение о чужих людях (Phase 87) ------


class _FakeSender:
    def __init__(self, id=1, username=None, first_name=None, last_name=None):
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name


def test_display_name_prefers_username():
    sender = _FakeSender(id=7, username="someone", first_name="Имя")
    assert _display_name(sender) == "@someone"


def test_display_name_falls_back_to_full_name():
    sender = _FakeSender(id=7, first_name="Иван", last_name="Петров")
    assert _display_name(sender) == "Иван Петров"


def test_display_name_falls_back_to_first_name_only():
    sender = _FakeSender(id=7, first_name="Иван")
    assert _display_name(sender) == "Иван"


def test_display_name_falls_back_to_id_when_no_name():
    sender = _FakeSender(id=42)
    assert _display_name(sender) == "42"


def test_display_name_handles_none_sender():
    assert _display_name(None) == "неизвестно"
