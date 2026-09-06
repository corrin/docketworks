#!/usr/bin/env python
"""Verify configured provider rows through the same metered probe as Integrations."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.ai.models import AIProvider  # noqa: E402 -- Django must be configured first
from apps.ai.services.provider_configuration import verify_provider  # noqa: E402


def main() -> int:
    """Test each configured row, including OpenAI; unused vendors need no credentials."""
    providers = AIProvider.objects.order_by("pk")
    if not providers.exists():
        print("AI: no providers configured; configure required vendors in Admin > Integrations")
        return 0
    for provider in providers:
        if provider.api_key is None:
            print(f"{provider.name}: not configured")
            continue
        model = verify_provider(provider)
        print(f"{provider.name}: verified {model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
