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

# Test Claude and Gemini via LLMService (chat)
for ptype in [AIProviderTypes.ANTHROPIC, AIProviderTypes.GOOGLE]:
    provider = AIProvider.objects.filter(provider_type=ptype).first()
    if not provider or not provider.api_key:
        print(f"{ptype}: Not configured")
        continue
    try:
        svc = LLMService(provider_type=ptype)
        resp = svc.get_text_response([{"role": "user", "content": "Say hi in 2 words"}])
        print(f"{provider.name}: {resp.strip()[:30]}")
    except Exception as e:
        print(f"{provider.name}: ERROR - {str(e)[:50]}")

# Test Mistral via SDK (OCR model - just validate key works)
provider = AIProvider.objects.filter(provider_type=AIProviderTypes.MISTRAL).first()
if provider and provider.api_key:
    try:
        client = Mistral(api_key=provider.api_key)
        models = client.models.list()
        print(f"Mistral: API key valid ({len(models.data)} models available)")
    except Exception as e:
        print(f"Mistral: ERROR - {str(e)[:50]}")
else:
    print("Mistral: Not configured")
