"""Smoke tests: the project boots, the API mounts, the gates are on."""

from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client

from apps.core.environment import validate_scrub_db_name
from config.settings import REQUIRED_ENV_VARS, validate_required_settings


def test_openapi_document_served() -> None:
    response = Client().get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Docketworks API"


def test_test_settings_supply_every_required_variable() -> None:
    """CI has no `.env`, so `settings_test` is the only source of these.

    A variable added to REQUIRED_ENV_VARS without a fallback here raises at
    settings import on any machine without a populated `.env` — which is every
    CI runner. That is not a test failure there but a collapse before the first
    check: mypy's Django plugin imports these settings to construct, so the
    whole backend job dies at the first step with an internal plugin error that
    names nothing about the missing variable. SESSION_REPLAY_STORAGE_ROOT did
    exactly that for seven consecutive runs.
    """
    source = (Path(settings.BASE_DIR) / "config" / "settings_test.py").read_text()
    unsupplied = [name for name in REQUIRED_ENV_VARS if f'"{name}"' not in source]
    assert unsupplied == []


def test_jwt_signing_key_is_explicit_and_separate_from_django_secret() -> None:
    assert settings.SIMPLE_JWT["SIGNING_KEY"] == settings.JWT_SIGNING_KEY
    assert settings.JWT_SIGNING_KEY != settings.SECRET_KEY


def test_scrub_db_name_suffix_rule_lives_in_one_place() -> None:
    # The rule has one implementation (ADR 0039); settings calls it at load so
    # the alias cannot exist with a bad name, and the scrub pipeline calls the
    # same function before its DROP SCHEMA.
    with pytest.raises(RuntimeError, match="_scrub"):
        validate_scrub_db_name("dw_msm_prod")
    validate_scrub_db_name("dw_msm_prod_scrub")


def test_short_jwt_signing_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SIGNING_KEY", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        validate_required_settings()


def test_reusing_django_secret_for_jwt_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    shared_key = "same-test-signing-key-at-least-32-bytes"
    monkeypatch.setenv("SECRET_KEY", shared_key)
    monkeypatch.setenv("JWT_SIGNING_KEY", shared_key)
    with pytest.raises(RuntimeError, match="distinct from SECRET_KEY"):
        validate_required_settings()
