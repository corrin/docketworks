"""Ignoring Xero objects created by finished E2E runs.

Business risk, both directions: E2E runs write real contacts, invoices and
quotes to a development Xero org; those survive the post-run database restore,
and the hourly sync would replay them into the clean database forever. But the
same filter, over-reaching, would discard a REAL Xero edit — and because the
sync cursor still advances, that edit would never be fetched again. And it must
never run against production data at all: these tests pin the two conditions
that together decide the skip, and the two guards that keep production exempt.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from django.conf import settings as django_settings
from django.test import override_settings
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from apps.xero import e2e_artifacts
from apps.xero.e2e_artifacts import (
    TEST_COMPANY_NAME,
    TEST_DATA_PREFIX,
    InboundXeroObject,
    drop_e2e_artifacts,
)


@dataclass
class _Contact:
    """An inbound Xero contact: carries its own company name."""

    name: str | None
    updated_date_utc: datetime | None


@dataclass
class _EmbeddedContact:
    name: str | None


@dataclass
class _Document:
    """An inbound Xero document: carries its company via an embedded contact."""

    contact: _EmbeddedContact
    updated_date_utc: datetime | None


def _document(contact_name: str, updated_at: datetime) -> _Document:
    return _Document(contact=_EmbeddedContact(name=contact_name), updated_date_utc=updated_at)


class _Windows:
    """A temporary windows file plus the timestamps the tests reason about."""

    def __init__(self, file: Path) -> None:
        self.file = file
        self.now = timezone.now()
        self.run_start = self.now - timedelta(minutes=30)
        self.run_end = self.now - timedelta(minutes=5)
        self.during_run = self.now - timedelta(minutes=20)

    def write(self, *, ended: bool) -> None:
        self.file.write_text(
            json.dumps(
                [
                    {
                        "run_id": "testrun1",
                        "started_at": self.run_start.isoformat(),
                        "ended_at": self.run_end.isoformat() if ended else None,
                    }
                ]
            )
        )


@pytest.fixture
def windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Windows:
    """Point the module at a per-test windows file (absent until written)."""
    file = tmp_path / "sync-windows.json"
    monkeypatch.setattr(e2e_artifacts, "E2E_SYNC_WINDOWS_FILE", file)
    return _Windows(file)


class TestDropE2EArtifacts:
    """The skip decision itself, with both production guards out of the way."""

    @pytest.fixture(autouse=True)
    def _debug_on(self, settings: SettingsWrapper) -> None:
        """override_settings cannot decorate a plain pytest class, so the
        DEBUG=True guard-release rides an autouse fixture instead."""
        settings.DEBUG = True

    def test_test_company_inside_closed_window_is_dropped(self, windows: _Windows) -> None:
        windows.write(ended=True)
        items: list[InboundXeroObject] = [
            _Contact(f"{TEST_DATA_PREFIX} Company 123", windows.during_run)
        ]

        assert drop_e2e_artifacts(items, "contacts") == []

    def test_fixture_company_inside_closed_window_is_dropped(self, windows: _Windows) -> None:
        """The standing fixture company is test data too.

        Test jobs hang off it, so the invoices and quotes a run raises are its
        documents, not those of a [TEST]-prefixed company.
        """
        windows.write(ended=True)
        items: list[InboundXeroObject] = [_Contact(TEST_COMPANY_NAME, windows.during_run)]

        assert drop_e2e_artifacts(items, "contacts") == []

    def test_ordinary_company_inside_closed_window_is_kept(self, windows: _Windows) -> None:
        """The window alone must never suppress; this is the over-reach guard.

        A real Xero edit landing inside a run's window would otherwise be
        discarded, and because the sync cursor still advances it would never
        be fetched again.
        """
        windows.write(ended=True)
        items: list[InboundXeroObject] = [_Contact("Morris Sheetmetal", windows.during_run)]

        assert drop_e2e_artifacts(items, "contacts") == items

    def test_test_company_outside_any_window_is_kept(self, windows: _Windows) -> None:
        windows.write(ended=True)
        items: list[InboundXeroObject] = [_Contact(f"{TEST_DATA_PREFIX} Company 123", windows.now)]

        assert drop_e2e_artifacts(items, "contacts") == items

    def test_open_window_suppresses_nothing(self, windows: _Windows) -> None:
        """The mid-run guarantee.

        While a run executes, inbound Xero data must behave exactly as it does
        in production — that round trip is what the run exercises. Fails if
        the ended_at condition is ever dropped.
        """
        windows.write(ended=False)
        items: list[InboundXeroObject] = [
            _Contact(f"{TEST_DATA_PREFIX} Company 123", windows.during_run)
        ]

        assert drop_e2e_artifacts(items, "contacts") == items

    def test_document_is_dropped_with_its_contact(self, windows: _Windows) -> None:
        """A suppressed contact's documents must go with it.

        The invoice, quote and purchase-order importers resolve their contact
        through resolve_company_from_xero_contact, which raises rather than
        skips when the company cannot be synced. Leaving the document behind
        would abort the whole sync run.
        """
        windows.write(ended=True)
        name = f"{TEST_DATA_PREFIX} Company 123"
        items: list[InboundXeroObject] = [
            _Contact(name, windows.during_run),
            _document(name, windows.during_run),
        ]

        assert drop_e2e_artifacts(items, "mixed") == []

    def test_absent_windows_file_suppresses_nothing(self, windows: _Windows) -> None:
        """The ordinary state of any machine that has never run E2E."""
        items: list[InboundXeroObject] = [
            _Contact(f"{TEST_DATA_PREFIX} Company 123", windows.during_run)
        ]

        assert drop_e2e_artifacts(items, "contacts") == items


class TestProductionGuards:
    """Production must never drop inbound data, whichever guard catches it.

    v1 gated on PRODUCTION_LIKE; v2 replaces it with two independent guards —
    DEBUG off means a production-like deployment, and the production tenant id
    means production data regardless of how the process is configured.
    """

    @override_settings(DEBUG=False)
    def test_debug_off_never_drops_anything(self, windows: _Windows) -> None:
        windows.write(ended=True)
        items: list[InboundXeroObject] = [
            _Contact(f"{TEST_DATA_PREFIX} Company 123", windows.during_run)
        ]

        assert drop_e2e_artifacts(items, "contacts") == items

    @override_settings(DEBUG=True)
    def test_production_tenant_never_drops_anything(self, windows: _Windows) -> None:
        """A dev-configured process synced to the production org is still
        production data — the tenant guard must hold on its own."""
        windows.write(ended=True)
        items: list[InboundXeroObject] = [
            _Contact(f"{TEST_DATA_PREFIX} Company 123", windows.during_run)
        ]

        kept = drop_e2e_artifacts(
            items, "contacts", active_tenant_id=django_settings.PRODUCTION_XERO_TENANT_ID
        )

        assert kept == items

    @override_settings(DEBUG=True)
    def test_non_production_tenant_with_debug_on_drops(self, windows: _Windows) -> None:
        """The guards must not over-reach either: a dev org under DEBUG is the
        one place the filter exists to run."""
        windows.write(ended=True)
        items: list[InboundXeroObject] = [
            _Contact(f"{TEST_DATA_PREFIX} Company 123", windows.during_run)
        ]

        assert drop_e2e_artifacts(items, "contacts", active_tenant_id="dev-tenant-id") == []
