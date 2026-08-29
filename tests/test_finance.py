from src.handlers.f9_finance import _looks_like_csv


def test_recognizes_by_extension():
    assert _looks_like_csv("выписка.csv", None) is True


def test_recognizes_by_mime_type():
    assert _looks_like_csv("файл", "text/csv") is True


def test_rejects_other_files():
    assert _looks_like_csv("фото.jpg", "image/jpeg") is False


def test_rejects_no_extension_no_mime():
    assert _looks_like_csv("документ", "application/octet-stream") is False
