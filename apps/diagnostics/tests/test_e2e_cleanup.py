"""Regression tests for the E2E recovery command."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Model, QuerySet

from apps.accounting.models import Invoice, Quote
from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.company.tests.job_fixtures import make_invoice, make_job, make_purchase_order, make_quote
from apps.diagnostics.management.commands.e2e_cleanup import TEST_COMPANY_NAME, Command
from apps.job.models import Job, QuoteSpreadsheet
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.quoting.models import SupplierPriceList

pytestmark = pytest.mark.django_db


STUBBED_COMMANDS = ("sync_sequences", "archive_test_contacts")


@pytest.fixture(autouse=True)
def invoked_commands(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Record the commands the cleanup delegates to instead of running them.

    sync_sequences' explicit COMMIT would escape pytest's database savepoint,
    and archive_test_contacts writes to Xero.
    """
    invoked: list[tuple[str, ...]] = []

    def record(command: str, *args: str) -> None:
        invoked.append((command, *args))
        if command not in STUBBED_COMMANDS:
            call_command(command, *args)

    monkeypatch.setattr("apps.diagnostics.management.commands.e2e_cleanup.call_command", record)
    return invoked


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

    assert "No test data found" in output
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


def test_a_company_archived_in_xero_is_the_mirror_not_residue(
    invoked_commands: list[tuple[str, ...]],
) -> None:
    """Xero cannot delete a contact; the archived mirror must survive every cleanup."""
    archived = Company.objects.create(
        name="[TEST] Archived In Xero", xero_archived=True, xero_last_modified="2026-08-08T00:00Z"
    )
    active = Company.objects.create(
        name="[TEST] Still Active", xero_last_modified="2026-08-08T00:00Z"
    )

    _run_cleanup("--confirm")

    assert Company.objects.filter(pk=archived.pk).exists()
    assert not Company.objects.filter(pk=active.pk).exists()
    assert ("archive_test_contacts", "--confirm") in invoked_commands


def test_dry_run_does_not_archive_in_xero(invoked_commands: list[tuple[str, ...]]) -> None:
    Company.objects.create(name="[TEST] Company", xero_last_modified="2026-08-08T00:00Z")

    _run_cleanup()

    assert all(command != "archive_test_contacts" for command, *_ in invoked_commands)
