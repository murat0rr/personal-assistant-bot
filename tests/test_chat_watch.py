from src.core.chat_watch import _chat_tag

# Чистая функция без похода в БД/Claude — тот же принцип, что у
# _is_quiet_hour/_should_send_nudge в test_task_nag.py. CRUD/батчинг/приём
# сообщений core/chat_watch.py и handlers/f_chat_watch.py трогают реальную
# Postgres и живой Bot API, которых здесь нет — это покрывается живой
# проверкой докером (см. SPEC.md, раздел Phase 99), не этим файлом.


# ---- _chat_tag — slugify заголовка чата под тег (Phase 87, не менялось) --


def test_chat_tag_lowercases_and_joins_with_dash():
    assert _chat_tag("Рабочий Чат") == "рабочий-чат"


def test_chat_tag_strips_punctuation():
    assert _chat_tag("Проект №1 (важное!)") == "проект-1-важное"


def test_chat_tag_falls_back_to_chat_when_empty():
    assert _chat_tag("...") == "chat"


def test_chat_tag_handles_single_word():
    assert _chat_tag("Семья") == "семья"
