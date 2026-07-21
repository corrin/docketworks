#!/usr/bin/env python
"""Validate AI provider API keys are configured and working."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from mistralai.client.sdk import Mistral

from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider
from apps.workflow.services.llm_service import LLMService


def validate_chat_provider(provider_type: str) -> str:
    provider = AIProvider.objects.filter(provider_type=provider_type).first()
    if not provider or not provider.api_key:
        raise RuntimeError(f"{provider_type}: Not configured")
    svc = LLMService(provider_type=provider_type)
    resp = svc.get_text_response([{"role": "user", "content": "Say hi in 2 words"}])
    return f"{provider.name}: {resp.strip()[:30]}"


def validate_mistral_provider() -> str:
    provider = AIProvider.objects.filter(provider_type=AIProviderTypes.MISTRAL).first()
    if not provider or not provider.api_key:
        raise RuntimeError("Mistral: Not configured")
    client = Mistral(api_key=provider.api_key)
    models = client.models.list()
    return f"Mistral: API key valid ({len(models.data)} models available)"


def main() -> None:
    for provider_type in (AIProviderTypes.ANTHROPIC, AIProviderTypes.GOOGLE):
        print(validate_chat_provider(provider_type))
    print(validate_mistral_provider())


if __name__ == "__main__":
    main()
