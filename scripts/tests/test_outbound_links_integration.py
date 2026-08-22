"""Every outbound link the app emits resolves, asked from an authenticated context (ADR 0050).

This is the slow-tier merge gate for dead links: it never runs in CI (no
vendor credentials there; CI stays hermetic) and is picked up by
``./scripts/ops/run_integration_tests.sh`` through the ``integration`` marker.
The fixture copies ``CompanyDefaults`` as well as the Xero token from the dev
database, so the Google folder ids, branding theme and payroll calendar it
checks are the real ones. Google is reached as the delegated Workspace user,
which needs ``GCP_CREDENTIALS`` — required, not optional: a run that silently
skipped Drive would report the deleted-doc case as green.

No ``assert_not_production_target`` here, unlike the payroll suite: the probe
writes nothing anywhere, and the run script already refuses a production
database before pytest starts.
"""

from __future__ import annotations

import os

import pytest

from scripts.ops.outbound_links_probe import (
    DriveLookup,
    GoogleIdentity,
    LiveXero,
    enumerate_links,
    google_credentials,
    render,
    requests_fetch,
    verify_all,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _credentials(integration_credentials: None) -> None:  # noqa: ARG001 -- the fixture's side effect is the dependency
    if not os.environ.get("GCP_CREDENTIALS"):
        raise RuntimeError(
            "GCP_CREDENTIALS is not set: the link probe verifies Google Drive files as the "
            "delegated Workspace user and cannot report on them without the key file."
        )


def test_every_outbound_link_resolves() -> None:
    # The dev database's company_email is the seed placeholder, so delegation
    # has nobody to impersonate there; the service account is the identity
    # that can answer on a dev box. PROBE_GOOGLE_AS=delegated on an instance
    # whose company_email is a real Workspace user.
    identity: GoogleIdentity = (
        "delegated" if os.environ.get("PROBE_GOOGLE_AS") == "delegated" else "service-account"
    )
    links = enumerate_links(sample=5, google_as=identity)

    report = verify_all(
        links,
        workers=16,
        fetch=requests_fetch,
        google_lookup=DriveLookup(credentials=lambda: google_credentials(identity)),
        xero=LiveXero(),
    )

    assert report.reachable, render(report)
    assert report.broken == [], render(report)
