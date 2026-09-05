from src.core.config import settings
from src.handlers.f_google_calendar import _SETUP_GUIDE, _guessed_redirect_uri


def test_guessed_redirect_uri_derives_from_miniapp_url():
    prev = settings.miniapp_url
    try:
        settings.miniapp_url = "https://shitinez.shop/miniapp/"
        assert _guessed_redirect_uri() == "https://shitinez.shop/google/oauth/callback"
    finally:
        settings.miniapp_url = prev


def test_guessed_redirect_uri_falls_back_when_miniapp_url_empty():
    prev = settings.miniapp_url
    try:
        settings.miniapp_url = ""
        assert _guessed_redirect_uri() == "https://<ваш-домен>/google/oauth/callback"
    finally:
        settings.miniapp_url = prev


def test_setup_guide_formats_without_error_and_mentions_env_vars():
    text = _SETUP_GUIDE.format(redirect_uri="https://example.com/google/oauth/callback")
    assert "GOOGLE_CLIENT_ID" in text
    assert "GOOGLE_CLIENT_SECRET" in text
    assert "GOOGLE_OAUTH_REDIRECT_URI" in text
    assert text.count("https://example.com/google/oauth/callback") == 2
