"""Regression tests for the E2E recovery command."""

from dataclasses import dataclass
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Model, QuerySet

from apps.accounting.models import Invoice, Quote
from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.company.tests.job_fixtures import make_invoice, make_job, make_purchase_order, make_quote
from apps.core.test_data import TEST_COMPANY_NAME
from apps.diagnostics.management.commands.e2e_cleanup import Command
from apps.job.models import Job, QuoteSpreadsheet
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.quoting.models import SupplierPriceList

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolate_sequence_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep sync_sequences' explicit COMMIT from escaping pytest's database savepoint."""
    real_call_command = call_command

    def skip_sequence_sync(command: str, *args: str, **kwargs: object) -> None:
        if command != "sync_sequences":
            real_call_command(command, *args, **kwargs)

    monkeypatch.setattr(
        "apps.diagnostics.management.commands.e2e_cleanup.call_command", skip_sequence_sync
    )


@dataclass(frozen=True)
class _XeroContact:
    """Fable: a local double for apps.xero.seeding.XeroContactRef — diagnostics
    and xero are independent layers, so this test may not import xero either."""

    name: str
    contact_id: str
    contact_status: str


@dataclass(frozen=True)
class _ArchiveOutcome:
    archived: tuple[str, ...]
    refused: dict[str, str]


@pytest.fixture(autouse=True)
def xero_archives(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """A fake demo organisation holding one active E2E contact; archive calls are recorded.

    Fable: stubbed at the Xero seams rather than at the command dispatch, so
    the guarantee under test — a confirmed cleanup archives the residue in
    Xero — survives a rewrite that stops going through call_command.
    """
    archived: list[list[str]] = []
    target = "apps.xero.management.commands.archive_test_contacts"
    in_xero = _XeroContact(name="[TEST] In Xero", contact_id="xero-1", contact_status="ACTIVE")
    monkeypatch.setattr(f"{target}.get_all_xero_contacts", lambda: [in_xero])
    monkeypatch.setattr(f"{target}.assert_not_production_target", lambda: None)
    monkeypatch.setattr(f"{target}.assert_xero_writes_enabled", lambda _operation: None)

    def record(contact_ids: list[str]) -> _ArchiveOutcome:
        archived.append(list(contact_ids))
        return _ArchiveOutcome(archived=tuple(contact_ids), refused={})

    monkeypatch.setattr(f"{target}.archive_contacts_in_xero", record)
    return archived


def _run_cleanup(*args: str) -> str:
    output = StringIO()
    call_command("e2e_cleanup", *args, stdout=output)
    return output.getvalue()


def test_dry_run_reports_without_deleting(office_staff: Staff) -> None:
    """An agent omitting --confirm must never turn an inspection into data loss."""
    company = Company.objects.create(name="[TEST] Company", xero_last_modified="2026-08-08T00:00Z")
    job = make_job(company, office_staff, name="[TEST] Job")

    output = _run_cleanup()

    assert "DRY RUN" in output
    assert Job.objects.filter(pk=job.pk).exists()
    assert Company.objects.filter(pk=company.pk).exists()


def test_confirm_deletes_test_rows_and_preserves_ordinary_rows(office_staff: Staff) -> None:
    """Cleanup must remove only the named E2E surface, not neighbouring development data."""
    test_company = Company.objects.create(
        name=TEST_COMPANY_NAME, xero_last_modified="2026-08-08T00:00Z"
    )
    test_person = Person.objects.create(name="[TEST] Person")
    CompanyPersonLink.objects.create(company=test_company, person=test_person)
    test_job = make_job(test_company, office_staff, name="[TEST] Job")

    ordinary_company = Company.objects.create(
        name="Ordinary Company", xero_last_modified="2026-08-08T00:00Z"
    )
    ordinary_person = Person.objects.create(name="Ordinary Person")
    CompanyPersonLink.objects.create(company=ordinary_company, person=ordinary_person)
    ordinary_job = make_job(ordinary_company, office_staff, name="Ordinary Job")

    output = _run_cleanup("--confirm")

    assert "Done." in output
    assert not Job.objects.filter(pk=test_job.pk).exists()
    assert not Person.objects.filter(pk=test_person.pk).exists()
    # The named company is seed data every UI-seeded spec selects by name —
    # cleanup removes what tests created ON it, never the company itself.
    assert Company.objects.filter(pk=test_company.pk).exists()
    assert Job.objects.filter(pk=ordinary_job.pk).exists()
    assert Person.objects.filter(pk=ordinary_person.pk).exists()
    assert Company.objects.filter(pk=ordinary_company.pk).exists()


def test_empty_named_test_company_is_not_test_data() -> None:
    """The reserved E2E company alone must read as a clean database."""
    test_company = Company.objects.create(
        name=TEST_COMPANY_NAME, xero_last_modified="2026-08-08T00:00Z"
    )

    output = _run_cleanup("--confirm")

    assert "No local test data found" in output
    assert Company.objects.filter(pk=test_company.pk).exists()


def test_confirm_deletes_legacy_prefix_companies(office_staff: Staff) -> None:
    """The legacy E2E name prefixes are residue and are removed with their rows."""
    legacy_company = Company.objects.create(
        name="E2E Test Client 42", xero_last_modified="2026-08-08T00:00Z"
    )
    legacy_job = make_job(legacy_company, office_staff, name="Legacy job")

    output = _run_cleanup("--confirm")

    assert "Done." in output
    assert not Job.objects.filter(pk=legacy_job.pk).exists()
    assert not Company.objects.filter(pk=legacy_company.pk).exists()


def test_confirm_deletes_company_scoped_invoice_without_job() -> None:
    """Invoices PROTECT on company too — a job-less invoice must not abort the cleanup."""
    test_company = Company.objects.create(
        name="[TEST] Invoice Company", xero_last_modified="2026-08-08T00:00Z"
    )
    invoice = make_invoice(test_company, job=None)

    output = _run_cleanup("--confirm")

    assert "Done." in output
    assert not Invoice.objects.filter(pk=invoice.pk).exists()
    assert not Company.objects.filter(pk=test_company.pk).exists()


def test_refuses_when_company_carries_quoting_data() -> None:
    """A deletable-looking company with scraper data is production data — refuse loudly."""
    test_company = Company.objects.create(
        name="[TEST] Supplier With Prices", xero_last_modified="2026-08-08T00:00Z"
    )
    SupplierPriceList.objects.create(supplier=test_company, file_name="prices.pdf")

    with pytest.raises(CommandError, match="quoting price_lists"):
        _run_cleanup("--confirm")

    assert Company.objects.filter(pk=test_company.pk).exists()


def test_handle_rejects_non_boolean_confirm_option() -> None:
    """Programmatic callers must not turn a truthy value into deletion approval."""
    with pytest.raises(TypeError, match="confirm option must be a boolean"):
        Command().handle(confirm="yes")


def test_confirm_deletes_protected_dependants(office_staff: Staff) -> None:
    """Adding invoices or purchasing rows must not make stale E2E data impossible to recover."""
    test_company = Company.objects.create(
        name="[TEST] Protected Company", xero_last_modified="2026-08-08T00:00Z"
    )
    job = make_job(test_company, office_staff, name="[TEST] Protected Job")
    invoice = make_invoice(test_company, job=job)
    quote = make_quote(test_company)
    quote.job = job
    quote.save(update_fields=["job"])
    sheet = QuoteSpreadsheet.objects.create(sheet_id="test-sheet", job=job)
    supplier = Company.objects.create(
        name="Ordinary Supplier", xero_last_modified="2026-08-08T00:00Z"
    )
    purchase_order = make_purchase_order(supplier)
    line = PurchaseOrderLine.objects.create(
        purchase_order=purchase_order,
        job=job,
        description="Test line",
        quantity=1,
    )

    _run_cleanup("--confirm")

    assert not Invoice.objects.filter(pk=invoice.pk).exists()
    assert not Quote.objects.filter(pk=quote.pk).exists()
    assert not QuoteSpreadsheet.objects.filter(pk=sheet.pk).exists()
    assert not PurchaseOrderLine.objects.filter(pk=line.pk).exists()
    assert PurchaseOrder.objects.filter(pk=purchase_order.pk).exists()


def test_confirm_rolls_back_when_a_delete_fails(
    office_staff: Staff, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newly protected relation must fail the cleanup without leaving half its rows deleted."""
    company = Company.objects.create(
        name="[TEST] Rollback Company", xero_last_modified="2026-08-08T00:00Z"
    )
    job = make_job(company, office_staff, name="[TEST] Rollback Job")
    invoice = make_invoice(company, job=job)
    original_delete = Command._delete_queryset

    def delete_then_fail(self: Command, label: str, queryset: QuerySet[Model]) -> None:
        original_delete(self, label, queryset)
        if label == "Invoices":
            raise RuntimeError("simulated cleanup failure")

    monkeypatch.setattr(Command, "_delete_queryset", delete_then_fail)

    with pytest.raises(RuntimeError, match="simulated cleanup failure"):
        _run_cleanup("--confirm")

    assert Invoice.objects.filter(pk=invoice.pk).exists()
    assert Job.objects.filter(pk=job.pk).exists()
    assert Company.objects.filter(pk=company.pk).exists()


def test_a_company_archived_in_xero_is_the_mirror_not_residue() -> None:
    """Xero cannot delete a contact, so its archived mirror must survive every cleanup."""
    archived = Company.objects.create(
        name="[TEST] Archived In Xero", xero_archived=True, xero_last_modified="2026-08-08T00:00Z"
    )

    _run_cleanup("--confirm")

    assert Company.objects.filter(pk=archived.pk).exists()


def test_confirm_archives_the_residue_in_xero_even_when_the_database_is_clean(
    xero_archives: list[list[str]],
) -> None:
    """The database is clean after every normal run; the residue that matters is in Xero."""
    _run_cleanup("--confirm")

    assert xero_archives == [["xero-1"]]


def test_dry_run_does_not_archive_in_xero(xero_archives: list[list[str]]) -> None:
    """An inspection must never write to the organisation."""
    Company.objects.create(name="[TEST] Company", xero_last_modified="2026-08-08T00:00Z")

    _run_cleanup()

    assert xero_archives == []


def test_the_xero_guard_trips_before_any_local_row_is_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused target (production, read-only) must not have already lost its local rows."""
    company = Company.objects.create(name="[TEST] Company", xero_last_modified="2026-08-08T00:00Z")

    def refuse() -> None:
        raise ValueError("production tenant")

    monkeypatch.setattr(
        "apps.xero.management.commands.archive_test_contacts.assert_not_production_target",
        refuse,
    )

    with pytest.raises(ValueError, match="production tenant"):
        _run_cleanup("--confirm")
    assert Company.objects.filter(pk=company.pk).exists()


def test_dependants_of_an_archived_company_are_still_residue() -> None:
    """A PO raised against a supplier archived later is a spec's leftovers, not the mirror."""
    archived = Company.objects.create(
        name="[TEST] Archived Supplier", xero_archived=True, xero_last_modified="2026-08-08T00:00Z"
    )
    po = make_purchase_order(archived)

    _run_cleanup("--confirm")

    assert not PurchaseOrder.objects.filter(pk=po.pk).exists()
    assert Company.objects.filter(pk=archived.pk).exists()
