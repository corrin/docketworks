#!/usr/bin/env python
"""Validate AI provider API keys are configured and working.

Deviation from v1: v1 validated Mistral separately via the ``mistralai`` SDK's
``client.models.list()`` (a non-chat capability probe). v2 has no vendor SDK
dependency for any provider — ADR 0041 routes every AI call through
``apps.ai.services.llm_client``, the single LiteLLM-backed gateway — so this
check validates Mistral the same way as the others: a live chat completion.
That drops the "how many models does this key see" signal v1 had, but proves
strictly more about what the app actually does with the key (the app itself
never lists models).
"""

import os
import sys
from pathlib import Path

# scripts/ops/restore_checks/ is three levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from apps.ai.enums import AIProviderTypes  # noqa: E402 -- Django must be configured first
from apps.ai.models import AIProvider  # noqa: E402
from apps.ai.services.llm_client import LLMConfigurationError, chat_completion  # noqa: E402

CHECKED_PROVIDER_TYPES = (
    AIProviderTypes.ANTHROPIC,
    AIProviderTypes.GOOGLE,
    AIProviderTypes.MISTRAL,
)


def validate_provider(provider_type: str) -> str:
    provider = AIProvider.objects.filter(provider_type=provider_type).first()
    if not provider or not provider.api_key:
        raise LLMConfigurationError(f"{provider_type}: Not configured")
    response = chat_completion("Say hi in 2 words", provider_type=provider_type)
    return f"{provider.name}: {response.strip()[:30]}"


def main() -> int:
    for provider_type in CHECKED_PROVIDER_TYPES:
        try:
            print(validate_provider(provider_type))
        except LLMConfigurationError as exc:
            print(f"ERROR: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
