"""Smoke tests: the project boots, the API mounts, the gates are on."""

import pytest
from django.conf import settings
from django.test import Client

from config.settings import validate_required_settings


def test_openapi_document_served() -> None:
    response = Client().get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Docketworks API"


def test_jwt_signing_key_is_explicit_and_separate_from_django_secret() -> None:
    assert settings.SIMPLE_JWT["SIGNING_KEY"] == settings.JWT_SIGNING_KEY
    assert settings.JWT_SIGNING_KEY != settings.SECRET_KEY


def test_short_jwt_signing_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SIGNING_KEY", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        validate_required_settings()


def test_reusing_django_secret_for_jwt_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SIGNING_KEY", settings.SECRET_KEY)
    with pytest.raises(RuntimeError, match="distinct from SECRET_KEY"):
        validate_required_settings()
