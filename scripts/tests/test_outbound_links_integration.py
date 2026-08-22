"""Every outbound link the app emits resolves, asked from an authenticated context (ADR 0050).

This is the slow-tier merge gate for dead links: it never runs in CI (no
vendor credentials there; CI stays hermetic) and is picked up by
``./scripts/ops/run_integration_tests.sh`` through the ``integration`` marker.
``integration_credentials`` copies every ``CompanyDefaults`` column from the
dev database along with the Xero token, so the Google folder ids, branding
theme and payroll calendar it checks are the instance's real ones; the
per-row tables (procedures, quote spreadsheets, invoices) are NOT copied, so
those are exercised by the operator run against an instance, and the Drive
path itself by the canary below. Google is reached as the delegated Workspace user,
which needs ``GCP_CREDENTIALS`` — required, not optional: a run that silently
skipped Drive would report the deleted-doc case as green.

No ``assert_not_production_target`` here, unlike the payroll suite: the probe
is read-only, the canary's only write is a throwaway file it deletes in its
``finally``, and the run script already refuses a production database before
pytest starts.
"""

from __future__ import annotations

import os

import pytest

from scripts.ops.outbound_links_probe import (
    DriveLookup,
    LiveXero,
    OutboundLink,
    enumerate_links,
    google_credentials,
    google_identity_from_env,
    render,
    requests_fetch,
    verify_all,
    verify_google_file,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _credentials(integration_credentials: None) -> None:  # noqa: ARG001 -- Fable: the fixture's side effect is the dependency
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
    identity = google_identity_from_env()
    links = enumerate_links(sample=5, google_as=identity)

    report = verify_all(
        links,
        workers=16,
        fetch=requests_fetch,
        google_lookup=DriveLookup(credentials=lambda: google_credentials(identity)),
        xero=LiveXero(),
    )

    assert report.reachable, render(report)
    # Fable: unreachable fails the gate too. A Drive or Xero that could not be
    # asked is not one that said yes, and every real failure mode — expired
    # token, quota, missing scope — arrives as unreachable, not broken.
    assert report.unreachable == [], render(report)
    assert report.broken == [], render(report)


def test_a_trashed_drive_file_is_reported_broken() -> None:
    """The motivating case, proven live every run rather than assumed from the instance's data.

    Fable: The dev database holds no Google ids (all NULL), so without this the
    Drive path would never be exercised by the gate. A throwaway file the
    identity owns is trashed, probed, then deleted for good.
    """
    identity = google_identity_from_env()
    lookup = DriveLookup(credentials=lambda: google_credentials(identity))
    service = lookup.drive()
    created = (
        service.files()
        .create(body={"name": "outbound-links-probe canary", "mimeType": "text/plain"}, fields="id")
        .execute()
    )
    file_id = str(created["id"])
    try:
        fresh = verify_google_file(
            OutboundLink(kind="google_file", source="canary", external_id=file_id), lookup=lookup
        )
        service.files().update(fileId=file_id, body={"trashed": True}).execute()
        trashed = verify_google_file(
            OutboundLink(kind="google_file", source="canary", external_id=file_id), lookup=lookup
        )
    finally:
        service.files().delete(fileId=file_id).execute()
    deleted = verify_google_file(
        OutboundLink(kind="google_file", source="canary", external_id=file_id), lookup=lookup
    )

    assert fresh.verdict == "ok", fresh
    assert trashed.verdict == "broken", trashed
    assert "trashed" in trashed.detail
    assert deleted.verdict == "broken", deleted
