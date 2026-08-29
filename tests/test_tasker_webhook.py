import pytest
from fastapi import HTTPException

from src.adapters.tasker_webhook import _verify_secret
from src.core.config import settings


def test_verify_secret_ok(monkeypatch):
    monkeypatch.setattr(settings, "tasker_webhook_secret", "s3cr3t")
    _verify_secret("s3cr3t")  # не должно бросить


def test_verify_secret_missing_header(monkeypatch):
    monkeypatch.setattr(settings, "tasker_webhook_secret", "s3cr3t")
    with pytest.raises(HTTPException) as exc:
        _verify_secret(None)
    assert exc.value.status_code == 401


def test_verify_secret_wrong_value(monkeypatch):
    monkeypatch.setattr(settings, "tasker_webhook_secret", "s3cr3t")
    with pytest.raises(HTTPException) as exc:
        _verify_secret("wrong")
    assert exc.value.status_code == 401


def test_verify_secret_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "tasker_webhook_secret", "")
    with pytest.raises(HTTPException):
        _verify_secret("anything")
