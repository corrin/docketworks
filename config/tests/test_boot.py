"""Smoke tests: the project boots, the API mounts, the gates are on."""

import importlib
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client

import config.settings
from apps.core.environment import validate_scrub_db_name
from config.settings import REQUIRED_ENV_VARS, validate_required_settings


def test_openapi_document_served() -> None:
    response = Client().get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Docketworks API"


def test_test_settings_supply_every_required_variable() -> None:
    """CI has no `.env`, so `settings_test` is the only source of these.

    Opus: a variable added to REQUIRED_ENV_VARS without a fallback here raises
    at settings import on any machine without a populated `.env`, which is every
    CI runner. That is not a test failure there but a collapse before the first
    check: mypy's Django plugin imports these settings to construct, so the
    backend job dies at its first step with an internal plugin error naming
    nothing about the variable. Hence a test rather than trust.
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


def test_aliases_admit_requests_and_their_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An instance answers on every alias `instance.sh --alias` gave it.

    Django rejects a request whose Host is outside ALLOWED_HOSTS with a 400
    and a form POST from an origin outside CSRF_TRUSTED_ORIGINS with a 403,
    so an alias that reaches nginx but not these two lists is a hostname that
    serves nothing. The module is reloaded because both lists are derived at
    import; the reload afterwards restores it.
    """
    monkeypatch.setenv("APP_DOMAIN_ALIASES", "office.example.test,second.example.test")
    try:
        reloaded = importlib.reload(config.settings)
        assert {"office.example.test", "second.example.test"} <= set(reloaded.ALLOWED_HOSTS)
        assert {"https://office.example.test", "https://second.example.test"} <= set(
            reloaded.CSRF_TRUSTED_ORIGINS
        )
    finally:
        monkeypatch.undo()
        importlib.reload(config.settings)
