"""The create_service_api_key command: creation, display-once, refusal."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import ServiceAPIKey

pytestmark = pytest.mark.django_db


def _run(*args: str) -> str:
    out = StringIO()
    call_command("create_service_api_key", *args, stdout=out)
    return out.getvalue()


def test_creates_key_with_default_name_and_prints_it_once() -> None:
    output = _run()

    key = ServiceAPIKey.objects.get(name="Chatbot Service")
    assert key.key
    assert key.is_active is True
    assert key.key in output
    assert "cannot be retrieved again" in output


def test_creates_key_with_custom_name() -> None:
    _run("--name", "Warehouse Sync")

    assert ServiceAPIKey.objects.filter(name="Warehouse Sync").exists()


def test_refuses_duplicate_name_without_rotating_or_reprinting() -> None:
    _run("--name", "Chatbot Service")
    original = ServiceAPIKey.objects.get(name="Chatbot Service")

    with pytest.raises(CommandError, match="already exists"):
        _run("--name", "Chatbot Service")

    original.refresh_from_db()
    assert ServiceAPIKey.objects.filter(name="Chatbot Service").count() == 1
    assert original.key  # unchanged row, key not rotated


def test_distinct_keys_per_creation() -> None:
    _run("--name", "First")
    _run("--name", "Second")

    first = ServiceAPIKey.objects.get(name="First")
    second = ServiceAPIKey.objects.get(name="Second")
    assert first.key != second.key
