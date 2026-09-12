#!/usr/bin/env python
"""Verify configured provider rows through the same metered probe as Integrations."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.ai.models import AIProvider  # noqa: E402 -- Django must be configured first
from apps.ai.services.provider_configuration import verify_provider  # noqa: E402
from apps.core.errors import InvalidInputError, UpstreamRefusedError  # noqa: E402


def main() -> int:
    """Test each configured row, including OpenAI; unused vendors need no credentials.

    Opus: every provider is probed before the gate answers, so one bad vendor
    cannot hide the state of the ones behind it — which is what an uncaught
    refusal did. The two refusals are not the same fact and are not treated the
    same: a rejected credential is misconfiguration this restore must fix, while
    a rate limit says only that today's allowance is spent, so it leaves the row
    unproven without failing a restore that is otherwise sound.
    """
    providers = AIProvider.objects.order_by("pk")
    if not providers.exists():
        print("AI: no providers configured; configure required vendors in Admin > Integrations")
        return 0
    rejected: list[str] = []
    for provider in providers:
        if provider.api_key is None:
            print(f"{provider.name}: not configured")
            continue
        try:
            model = verify_provider(provider)
        except UpstreamRefusedError as exc:
            print(f"{provider.name}: NOT PROVEN — {exc}")
            continue
        except InvalidInputError as exc:
            print(f"{provider.name}: REJECTED — {exc}")
            rejected.append(provider.name)
            continue
        print(f"{provider.name}: verified {model}")
    if rejected:
        print(f"AI: rejected configuration on {', '.join(rejected)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
