"""What the organisation-driven sweep recognises as E2E residue, and what it spares."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounting.types import DocumentResult
from apps.core.test_data import TEST_COMPANY_NAME
from apps.xero.contacts import ArchiveOutcome

SWEEP = "apps.diagnostics.management.commands.e2e_xero_sweep"
RESIDUE = "apps.diagnostics.services.e2e_xero_residue"


@dataclass(frozen=True)
class FakeContact:
    """A Xero contact, as the SDK hands one back."""

    name: str
    contact_id: str
    contact_status: str = "ACTIVE"


@dataclass(frozen=True)
class FakeDocument:
    """A Xero invoice, quote or purchase order, keyed the way its SDK model is."""

    contact: FakeContact
    status: str
    invoice_id: str | None = None
    invoice_number: str | None = None
    quote_id: str | None = None
    quote_number: str | None = None
    purchase_order_id: str | None = None
    purchase_order_number: str | None = None


def invoice(contact: FakeContact, number: str, status: str = "AUTHORISED") -> FakeDocument:
    return FakeDocument(
        contact=contact, status=status, invoice_id=f"inv-{number}", invoice_number=number
    )


def quote(contact: FakeContact, number: str, status: str = "DRAFT") -> FakeDocument:
    return FakeDocument(
        contact=contact, status=status, quote_id=f"quo-{number}", quote_number=number
    )


def purchase_order(contact: FakeContact, number: str, status: str = "AUTHORISED") -> FakeDocument:
    return FakeDocument(
        contact=contact,
        status=status,
        purchase_order_id=f"po-{number}",
        purchase_order_number=number,
    )


class RecordingOrganisation:
    """A fake demo org that accepts everything and remembers what it was asked."""

    def __init__(self) -> None:
        self.timeline: list[tuple[str, str]] = []

    def _record(self, kind: str, external_id: str) -> DocumentResult:
        self.timeline.append((kind, external_id))
        return DocumentResult(success=True, external_id=external_id)

    def delete_invoice(self, external_id: str) -> DocumentResult:
        return self._record("invoice", external_id)

    def delete_quote(self, external_id: str) -> DocumentResult:
        return self._record("quote", external_id)

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        return self._record("purchase order", external_id)

    def archive(self, contact_ids: Sequence[str]) -> ArchiveOutcome:
        self.timeline.extend(("contact", contact_id) for contact_id in contact_ids)
        return ArchiveOutcome(archived=tuple(contact_ids), refused={})

    def ids_of(self, kind: str) -> set[str]:
        return {external_id for touched, external_id in self.timeline if touched == kind}

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.timeline]


STANDING = FakeContact(name=TEST_COMPANY_NAME, contact_id="contact-standing")
E2E_SUPPLIER = FakeContact(name="[TEST] Supplier 7", contact_id="contact-e2e")
LEGACY = FakeContact(name="E2E Test Client 3", contact_id="contact-legacy")
ARCHIVED_E2E = FakeContact(
    name="[TEST] Old Supplier", contact_id="contact-old", contact_status="ARCHIVED"
)
REAL_CUSTOMER = FakeContact(name="Real Customer Ltd", contact_id="contact-real")


@pytest.fixture
def organisation(monkeypatch: pytest.MonkeyPatch) -> RecordingOrganisation:
    """A fake org whose guards pass and whose every removal is recorded."""
    recorder = RecordingOrganisation()
    monkeypatch.setattr(f"{RESIDUE}.assert_not_production_target", lambda: None)
    monkeypatch.setattr(f"{RESIDUE}.assert_xero_writes_enabled", lambda _operation: None)
    monkeypatch.setattr(f"{RESIDUE}.get_provider", lambda: recorder)
    monkeypatch.setattr(f"{RESIDUE}.archive_contacts_in_xero", recorder.archive)
    return recorder


def load_organisation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    contacts: Sequence[FakeContact] = (),
    invoices: Sequence[FakeDocument] = (),
    quotes: Sequence[FakeDocument] = (),
    purchase_orders: Sequence[FakeDocument] = (),
) -> None:
    """Make the fake organisation hold exactly these objects."""
    held: dict[str, Sequence[object]] = {
        "contacts": contacts,
        "invoices": invoices,
        "quotes": quotes,
        "purchase_orders": purchase_orders,
    }

    def read(entity_name: str) -> Iterator[object]:
        return iter(held[entity_name])

    monkeypatch.setattr(f"{SWEEP}.iter_xero_entities", read)


def run_sweep(*args: str) -> str:
    output = StringIO()
    call_command("e2e_xero_sweep", *args, stdout=output)
    return output.getvalue()


def test_documents_on_the_standing_company_are_swept_but_it_stays_active(
    monkeypatch: pytest.MonkeyPatch, organisation: RecordingOrganisation
) -> None:
    """Specs raise their invoices on the fixture company, which every later spec selects by name."""
    load_organisation(
        monkeypatch,
        contacts=[STANDING],
        invoices=[invoice(STANDING, "INV-001")],
        quotes=[quote(STANDING, "QU-001")],
    )

    run_sweep("--confirm")

    assert organisation.ids_of("invoice") == {"inv-INV-001"}
    assert organisation.ids_of("quote") == {"quo-QU-001"}
    assert organisation.ids_of("contact") == set()


def test_a_real_customer_is_never_touched(
    monkeypatch: pytest.MonkeyPatch, organisation: RecordingOrganisation
) -> None:
    """The organisation is a restored copy of production; sweeping its data would be destruction."""
    load_organisation(
        monkeypatch,
        contacts=[REAL_CUSTOMER],
        invoices=[invoice(REAL_CUSTOMER, "INV-900")],
        purchase_orders=[purchase_order(REAL_CUSTOMER, "PO-900")],
    )

    output = run_sweep("--confirm")

    assert organisation.timeline == []
    assert "No E2E residue" in output


def test_e2e_contacts_are_archived_after_their_documents_are_deleted(
    monkeypatch: pytest.MonkeyPatch, organisation: RecordingOrganisation
) -> None:
    """Xero refuses to archive a contact with transactions, so the order is the whole fix."""
    load_organisation(
        monkeypatch,
        contacts=[E2E_SUPPLIER, LEGACY],
        purchase_orders=[purchase_order(E2E_SUPPLIER, "PO-1")],
    )

    run_sweep("--confirm")

    assert organisation.kinds() == ["purchase order", "contact", "contact"]
    assert organisation.ids_of("contact") == {"contact-e2e", "contact-legacy"}


def test_documents_xero_has_already_removed_are_skipped(
    monkeypatch: pytest.MonkeyPatch, organisation: RecordingOrganisation
) -> None:
    """Re-deleting a DELETED document is a refusal, so a swept org would report it forever."""
    load_organisation(
        monkeypatch,
        contacts=[STANDING],
        invoices=[
            invoice(STANDING, "INV-001", status="DELETED"),
            invoice(STANDING, "INV-002", status="VOIDED"),
            invoice(STANDING, "INV-003"),
        ],
    )

    run_sweep("--confirm")

    assert organisation.ids_of("invoice") == {"inv-INV-003"}


def test_a_contact_already_archived_is_not_archived_again(
    monkeypatch: pytest.MonkeyPatch, organisation: RecordingOrganisation
) -> None:
    """An archived contact is the organisation's settled state, not residue to act on."""
    load_organisation(monkeypatch, contacts=[ARCHIVED_E2E, E2E_SUPPLIER])

    run_sweep("--confirm")

    assert organisation.ids_of("contact") == {"contact-e2e"}


def test_dry_run_reports_without_touching_the_organisation(
    monkeypatch: pytest.MonkeyPatch, organisation: RecordingOrganisation
) -> None:
    """An operator inspecting the residue must not thereby remove it."""
    load_organisation(
        monkeypatch, contacts=[E2E_SUPPLIER], invoices=[invoice(E2E_SUPPLIER, "INV-001")]
    )

    output = run_sweep()

    assert "DRY RUN" in output
    assert "2 objects would be removed" in output
    assert organisation.timeline == []


def test_an_undocumented_contact_status_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A status outside ACTIVE/ARCHIVED must stop the sweep, never be read as 'not residue'.

    No fake organisation: the refusal happens while reading Xero, before
    anything could be removed, which is the point.
    """
    load_organisation(
        monkeypatch,
        contacts=[FakeContact(name="[TEST] Erased", contact_id="x", contact_status="GDPRREQUEST")],
    )

    with pytest.raises(ValueError, match="GDPRREQUEST"):
        run_sweep("--confirm")
