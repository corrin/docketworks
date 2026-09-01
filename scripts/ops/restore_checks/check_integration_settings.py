#!/usr/bin/env python
"""Prove each IntegrationSettings credential against the real service.

Runs after ``manage.py load_integration_settings`` has applied the instance's
rendered credentials (scripts/server/instance.sh) or after an operator enters
a value on Admin > Integrations. Each credential is exercised the way the app
uses it (ADR 0050): the Maps key by one live Address Validation call, the
phone provider by a real portal login when the integration is enabled. A
failure propagates with its traceback; the non-zero exit is the answer.
"""

from scripts.bootstrap import setup_django

setup_django()

from apps.company.services.geocoding_service import search_places  # noqa: E402 -- Django first
from apps.core.models import IntegrationSettings  # noqa: E402
from apps.crm.services.phone_call_service import verify_portal_login  # noqa: E402

PROBE_ADDRESS = "1 Queen Street, Auckland"


def main() -> None:
    settings = IntegrationSettings.get_solo()

    candidates = search_places(PROBE_ADDRESS, limit=1)
    if not candidates:
        raise SystemExit(f"Google Maps returned no candidate for {PROBE_ADDRESS!r}")
    print(f"Google Maps: {PROBE_ADDRESS!r} -> {candidates[0].formatted_address}")

    if not settings.phone_provider_enabled:
        print("Phone provider: disabled")
        return
    verify_portal_login()
    print("Phone provider: portal login succeeded")


if __name__ == "__main__":
    main()
