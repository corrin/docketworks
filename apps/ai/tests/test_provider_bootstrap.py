"""Exercise the actual instance renderer and shared provider loader together."""

import os
import subprocess
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider
from apps.ai.services.llm_client import resolve_target
from apps.ai.services.provider_configuration import ProviderCreate, create_provider

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[3]


def render(tmp_path: Path, **values: str) -> Path:
    """Run production rendering with optional vendors absent and real JSON metacharacters."""
    environment = dict(os.environ)
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_MODEL_NAME",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "MISTRAL_API_KEY",
        "AI_DEFAULT_PROVIDER",
    ):
        environment[name] = ""
    environment.update(values)
    subprocess.run(  # noqa: S603 — fixed repository renderer with controlled fixture arguments
        [
            "/bin/bash",
            "-c",
            'source "$1"; chown() { :; }; log() { :; }; render_ai_providers_fixture "$2" test',
            "_",
            str(ROOT / "scripts/server/instance.sh"),
            str(tmp_path),
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return tmp_path / ".fixtures/ai_providers.json"


def test_fresh_openai_only_setup_is_repeatable_and_preserves_edits(tmp_path: Path) -> None:
    """Only supplied vendors are created; reconfiguration cannot overwrite administrator edits."""
    fixture = render(
        tmp_path,
        OPENAI_API_KEY='key"with\\characters',
        OPENAI_MODEL_NAME="test-model",
        AI_DEFAULT_PROVIDER="OpenAI",
    )
    call_command("load_ai_providers", str(fixture))
    provider = AIProvider.objects.get()
    assert provider.api_key == 'key"with\\characters'
    assert provider.default
    assert resolve_target().model == "openai/test-model"
    provider.name = "Administrator's model"
    provider.model_name = "changed-model"
    provider.api_key = "rotated-key"
    provider.save()
    call_command("load_ai_providers", str(fixture))
    assert AIProvider.objects.count() == 1
    provider.refresh_from_db()
    assert provider.api_key == "rotated-key" and provider.model_name == "changed-model"
    assert fixture.stat().st_mode & 0o777 == 0o600


def test_existing_other_vendor_does_not_block_openai(tmp_path: Path) -> None:
    """Adding OpenAI preserves the existing vendor's key and application-default selection."""
    previous = create_provider(
        ProviderCreate(
            name="Custom Gemini",
            provider_type=AIProviderTypes.GOOGLE,
            api_key="retained",
            model_name="chosen-model",
        )
    )
    previous.default = True
    previous.save()
    fixture = render(
        tmp_path,
        OPENAI_API_KEY="new-key",
        OPENAI_MODEL_NAME="test-model",
        AI_DEFAULT_PROVIDER="OpenAI",
    )
    call_command("load_ai_providers", str(fixture))
    assert AIProvider.objects.count() == 2
    assert AIProvider.objects.get(default=True).pk == previous.pk
    assert AIProvider.objects.get(pk=previous.pk).api_key == "retained"
    assert resolve_target(AIProviderTypes.OPENAI).model == "openai/test-model"


def test_exact_empty_seed_is_refilled_but_ambiguous_entries_are_refused(tmp_path: Path) -> None:
    """A scrubbed seed can be rehydrated; different incomplete models need an operator choice."""
    provider = AIProvider.objects.create(
        name="OpenAI", provider_type="OpenAI", model_name="test-model"
    )
    fixture = render(tmp_path, OPENAI_API_KEY="new-key", OPENAI_MODEL_NAME="test-model")
    call_command("load_ai_providers", str(fixture))
    provider.refresh_from_db()
    assert provider.api_key == "new-key"
    provider.api_key = None
    provider.name = "Ambiguous"
    provider.save()
    with pytest.raises(CommandError, match="require attention"):
        call_command("load_ai_providers", str(fixture))
    assert AIProvider.objects.count() == 1
    assert AIProvider.objects.get().api_key is None


def test_partial_credentials_fail_without_partial_writes(tmp_path: Path) -> None:
    """A key without its requested model fails before any seed becomes usable."""
    fixture = render(tmp_path, OPENAI_API_KEY="sensitive-key", GEMINI_API_KEY="another-key")
    with pytest.raises(CommandError, match="requires a model") as error:
        call_command("load_ai_providers", str(fixture))
    assert "sensitive-key" not in str(error.value)
    assert not AIProvider.objects.exists()


def test_scrubbed_database_can_be_reseeded(tmp_path: Path) -> None:
    """The loader operates after migrations even when the scrub removed every provider."""
    fixture = render(tmp_path, OPENAI_API_KEY="new-key", OPENAI_MODEL_NAME="test-model")
    call_command("load_ai_providers", str(fixture))
    AIProvider.objects.all().delete()
    call_command("load_ai_providers", str(fixture))
    assert AIProvider.objects.get().api_key == "new-key"
