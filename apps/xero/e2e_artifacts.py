"""Ignore Xero objects created by finished E2E runs. Development only.

E2E runs against a live Xero organisation with writes enabled, so the contacts,
invoices and quotes a run creates persist in Xero after the run's database has
been restored from backup. The hourly Xero sync then re-imports them into the
clean database. This module stops the objects changed inside a recorded run;
contacts touched later are handled by e2e_cleanup archiving them in Xero
(``archive_test_contacts``), after which they mirror back archived.

An inbound Xero object is skipped only when *both* hold:

1. its timestamp falls inside a closed E2E run window, and
2. it belongs to a test company.

Neither is sufficient alone. The window alone would also discard genuine Xero
changes that happened to land inside it. The name alone is equally true while a
run is executing, and would blind the inbound path the run exists to exercise.

Run windows live in a temp file written by the E2E harness, not in the database:
teardown restores the database from a backup taken before the run, so database
state cannot describe a run that has just finished. Written by
frontend/tests/scripts/e2e-sync-windows.ts.
"""

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Protocol

from django.conf import settings

from apps.core.test_data import is_test_company_name
from apps.xero.operator_guards import is_production_tenant

logger = logging.getLogger(__name__)


class XeroContactLike(Protocol):
    """The embedded contact a Xero document carries."""

    name: str | None


class InboundXeroObject(Protocol):
    """Structural view of the Xero SDK objects the sync feeds through here.

    The SDK types share no base class, and only some carry a company: contacts
    hold their own `name`, documents hold a `contact`, and accounts and stock
    hold neither. This declares the one attribute they all have; the rest are
    read defensively.
    """

    updated_date_utc: datetime | None


# Fixed path so the backend and the E2E harness agree without one telling the
# other; same convention as the E2E lock file. Absent on any machine that has
# never run E2E, which is what keeps this module inert.
E2E_SYNC_WINDOWS_FILE = Path(tempfile.gettempdir()) / "docketworks-e2e-sync-windows.json"
#: The harness's own lock (frontend/tests/scripts/e2e-reset.ts and friends):
#: present exactly while a suite is running.
E2E_LOCK_FILE = Path(tempfile.gettempdir()) / "playwright-e2e.lock"

# The names themselves live in apps/core/test_data.py, the one home every
# reader may import.


def get_closed_e2e_windows() -> list[tuple[datetime, datetime]]:
    """Finished E2E runs, as (started_at, ended_at) pairs.

    A run still in progress has no `ended_at` and is skipped: while tests
    execute, inbound Xero data must behave exactly as it does in production,
    because that round trip is what the run exercises.
    """
    if not E2E_SYNC_WINDOWS_FILE.exists():
        return []

    return [
        (
            datetime.fromisoformat(entry["started_at"]),
            datetime.fromisoformat(entry["ended_at"]),
        )
        for entry in json.loads(E2E_SYNC_WINDOWS_FILE.read_text())
        if entry["ended_at"]
    ]


def _owning_company_name(item: InboundXeroObject) -> str | None:
    """Name of the company an inbound Xero object belongs to.

    A contact carries its own name. Documents — invoices, quotes, bills,
    purchase orders, credit notes — carry an embedded contact. Entities with no
    company at all, such as accounts and stock, return None and are never
    skipped.
    """
    contact: XeroContactLike | None = getattr(item, "contact", None)
    if contact is not None:
        return contact.name

    name: str | None = getattr(item, "name", None)
    return name


def _is_e2e_artifact(
    item: InboundXeroObject, closed_windows: list[tuple[datetime, datetime]]
) -> bool:
    """Report whether this Xero object was created by a finished E2E run."""
    updated_at: datetime | None = getattr(item, "updated_date_utc", None)
    if updated_at is None:
        return False

    if not is_test_company_name(_owning_company_name(item)):
        return False

    return any(start <= updated_at <= end for start, end in closed_windows)


def _production_guarded(active_tenant_id: str | None) -> bool:
    """Report whether dropping is forbidden in this environment.

    v1 gated on ``settings.PRODUCTION_LIKE``, which v2 does not carry. Two
    independent guards replace it — production must never drop inbound data:

    - ``DEBUG`` off means a production-like deployment.
    - The active tenant being the production organisation means production
      data regardless of how the process is configured.
    """
    if not settings.DEBUG:
        return True
    return active_tenant_id is not None and is_production_tenant(active_tenant_id)


def drop_e2e_artifacts(
    items: list[InboundXeroObject],
    entity_type: str,
    active_tenant_id: str | None = None,
) -> list[InboundXeroObject]:
    """Remove objects created by finished E2E runs from an inbound batch.

    Filtering the batch before it reaches the sync function is deliberate: the
    invoice, quote and purchase-order importers resolve their contact through
    ``resolve_company_from_xero_contact``, which raises rather than skips when a
    company cannot be synced. Dropping a suppressed contact and the documents
    that reference it together keeps that path from ever being reached.
    """
    if _production_guarded(active_tenant_id):
        return items

    closed_windows = get_closed_e2e_windows()
    if not closed_windows:
        return items

    kept = [item for item in items if not _is_e2e_artifact(item, closed_windows)]
    dropped = len(items) - len(kept)
    if dropped:
        logger.info("Skipped %d %s created by a finished E2E run", dropped, entity_type)
    return kept
