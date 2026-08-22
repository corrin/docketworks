#!/usr/bin/env python
"""Verify the IntegrationSettings row is present and its Google Maps key works.

Runs after ``manage.py load_integration_settings`` has applied the instance's
rendered credentials (scripts/server/instance.sh) or after an operator enters
the key on Admin > Integrations. The Maps key is
proven with one live Address Validation call, the way check_ai_providers
proves an AI key with a live completion (ADR 0050). The phone provider is
reported, not called: its only client is a portal scrape that the Beat task
exercises.
"""

import sys

from scripts.bootstrap import setup_django

setup_django()

from django.core.exceptions import ImproperlyConfigured  # noqa: E402 -- Django set up above

from apps.company.services.geocoding_service import (  # noqa: E402
    GeocodingError,
    geocode_address,
)
from apps.core.models import IntegrationSettings  # noqa: E402

PROBE_ADDRESS = "1 Queen Street, Auckland"


def main() -> int:
    try:
        settings = IntegrationSettings.get_solo()
    except ImproperlyConfigured as exc:
        print(f"ERROR: {exc}")
        return 1

    try:
        result = geocode_address(PROBE_ADDRESS)
    except GeocodingError as exc:
        print(f"ERROR: Google Maps: {exc}")
        return 1
    if result is None:
        print(f"ERROR: Google Maps returned no candidate for {PROBE_ADDRESS!r}")
        return 1
    print(f"Google Maps configured: {PROBE_ADDRESS!r} -> {result.formatted_address}")

    phone_configured = bool(
        settings.phone_provider_base_url
        and settings.phone_provider_username
        and settings.phone_provider_password
        and settings.phone_provider_account_code
    )
    downloads = "on" if settings.phone_provider_downloads_enabled else "off"
    state = "configured" if phone_configured else "not configured"
    print(f"Phone provider: {state}, downloads {downloads}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
