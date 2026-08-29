from src.handlers.f_question import _is_pdf


def test_recognizes_by_extension():
    assert _is_pdf("домашка.pdf", None) is True


def test_recognizes_by_mime_type():
    assert _is_pdf("файл", "application/pdf") is True


def test_rejects_other_files():
    assert _is_pdf("фото.jpg", "image/jpeg") is False


def test_rejects_no_extension_no_mime():
    assert _is_pdf("документ", "application/octet-stream") is False
