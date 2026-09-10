"""Regression tests for the E2E recovery command."""

import uuid
from collections.abc import Sequence
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Model, QuerySet
from pytest_django.fixtures import SettingsWrapper

from apps.accounting.models import Invoice, Quote
from apps.accounting.types import DocumentResult
from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.company.tests.job_fixtures import make_invoice, make_job, make_purchase_order, make_quote
from apps.core.test_data import TEST_COMPANY_NAME, TEST_DATA_PREFIX, silent_wav
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.crm.services.phone_call_service import store_recording_bytes
from apps.crm.tests.helpers import make_call, make_recording
from apps.diagnostics.management.commands.e2e_cleanup import Command
from apps.job.models import Job, QuoteSpreadsheet
from apps.process.models import Acknowledgement, Form, FormEntry
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.quoting.models import SupplierPriceList
from apps.xero.contacts import ArchiveOutcome

pytestmark = pytest.mark.django_db

CLEANUP = "apps.diagnostics.management.commands.e2e_cleanup"
#: Both commands remove through this module, so its seams are where a fake
#: organisation belongs — the guarantee under test is what reaches Xero, not
#: which command reached it.
RESIDUE = "apps.diagnostics.services.e2e_xero_residue"


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


class RecordingOrganisation:
    """A fake demo org that accepts everything and remembers the order it was asked.

    One timeline for documents and contacts together, because the ordering
    between them is the guarantee: Xero refuses to archive a contact that
    still has transactions against it, so archiving first silently leaves the
    residue behind.
    """

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

    def kinds(self) -> list[str]:
        """The kinds touched, in the order Xero saw them."""
        return [kind for kind, _ in self.timeline]

    def ids_of(self, kind: str) -> set[str]:
        """The ids of one kind that reached Xero."""
        return {external_id for touched, external_id in self.timeline if touched == kind}


@pytest.fixture(autouse=True)
def xero(monkeypatch: pytest.MonkeyPatch) -> RecordingOrganisation:
    """A fake demo organisation; the guards pass and every removal is recorded."""
    organisation = RecordingOrganisation()
    monkeypatch.setattr(f"{RESIDUE}.assert_not_production_target", lambda: None)
    monkeypatch.setattr(f"{RESIDUE}.assert_xero_writes_enabled", lambda _operation: None)
    monkeypatch.setattr(f"{RESIDUE}.get_provider", lambda: organisation)
    monkeypatch.setattr(f"{RESIDUE}.archive_contacts_in_xero", organisation.archive)
    return organisation


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


def test_confirm_removes_the_run_s_documents_and_contacts_from_xero(
    office_staff: Staff, xero: RecordingOrganisation
) -> None:
    """A run's Xero writes must not outlive it — that is the whole point of the teardown."""
    company = Company.objects.create(
        name="[TEST] Company",
        xero_contact_id="contact-1",
        xero_last_modified="2026-08-08T00:00Z",
    )
    job = make_job(company, office_staff, name="[TEST] Job")
    invoice = make_invoice(company, job=job)
    quote = make_quote(company, job=job)
    order = make_purchase_order(company)
    order.xero_id = uuid.uuid4()
    order.save(update_fields=["xero_id"])

    _run_cleanup("--confirm")

    assert xero.ids_of("invoice") == {str(invoice.xero_id)}
    assert xero.ids_of("quote") == {str(quote.xero_id)}
    assert xero.ids_of("purchase order") == {str(order.xero_id)}
    assert xero.ids_of("contact") == {"contact-1"}


def test_documents_are_removed_before_their_contact_is_archived(
    office_staff: Staff, xero: RecordingOrganisation
) -> None:
    """Xero refuses to archive a contact with transactions, so the order is the fix."""
    company = Company.objects.create(
        name="[TEST] Company",
        xero_contact_id="contact-1",
        xero_last_modified="2026-08-08T00:00Z",
    )
    job = make_job(company, office_staff, name="[TEST] Job")
    make_invoice(company, job=job)

    _run_cleanup("--confirm")

    assert xero.kinds() == ["invoice", "contact"]


def test_documents_on_the_standing_company_are_removed_but_it_is_not_archived(
    office_staff: Staff, xero: RecordingOrganisation
) -> None:
    """Specs raise their invoices on the fixture company, which every later spec still selects."""
    standing = Company.objects.create(
        name=TEST_COMPANY_NAME,
        xero_contact_id="contact-standing",
        xero_last_modified="2026-08-08T00:00Z",
    )
    job = make_job(standing, office_staff, name="[TEST] Job")
    invoice = make_invoice(standing, job=job)

    _run_cleanup("--confirm")

    assert xero.ids_of("invoice") == {str(invoice.xero_id)}
    assert xero.ids_of("contact") == set()
    assert Company.objects.filter(pk=standing.pk).exists()


def test_a_purchase_order_never_pushed_to_xero_is_not_deleted_there(
    xero: RecordingOrganisation,
) -> None:
    """A draft order has no Xero id, so the organisation holds nothing to remove for it."""
    supplier = Company.objects.create(
        name="[TEST] Supplier", xero_last_modified="2026-08-08T00:00Z"
    )
    make_purchase_order(supplier)

    _run_cleanup("--confirm")

    assert xero.ids_of("purchase order") == set()


def test_a_clean_database_removes_nothing_from_xero(xero: RecordingOrganisation) -> None:
    """Local rows are the only record of what a run wrote; without them there is nothing to undo.

    The organisation-wide question — what residue does Xero still hold —
    belongs to e2e_xero_sweep, which reads Xero rather than the database.
    """
    _run_cleanup("--confirm")

    assert xero.timeline == []


def test_dry_run_does_not_touch_xero(office_staff: Staff, xero: RecordingOrganisation) -> None:
    """An inspection must never write to the organisation."""
    company = Company.objects.create(
        name="[TEST] Company",
        xero_contact_id="contact-1",
        xero_last_modified="2026-08-08T00:00Z",
    )
    make_invoice(company, job=make_job(company, office_staff, name="[TEST] Job"))

    _run_cleanup()

    assert xero.timeline == []


def test_the_xero_guard_trips_before_any_local_row_is_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused target (production, read-only) must not have already lost its local rows."""
    company = Company.objects.create(name="[TEST] Company", xero_last_modified="2026-08-08T00:00Z")

    def refuse() -> None:
        raise ValueError("production tenant")

    monkeypatch.setattr(f"{RESIDUE}.assert_not_production_target", refuse)

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


def test_a_company_archived_in_xero_is_not_asked_to_archive_again(
    xero: RecordingOrganisation,
) -> None:
    """An archived company is the organisation's mirror, so re-archiving it is noise."""
    Company.objects.create(
        name="[TEST] Archived Supplier",
        xero_contact_id="contact-archived",
        xero_archived=True,
        xero_last_modified="2026-08-08T00:00Z",
    )
    Company.objects.create(
        name="[TEST] Active Supplier",
        xero_contact_id="contact-active",
        xero_last_modified="2026-08-08T00:00Z",
    )

    _run_cleanup("--confirm")

    assert xero.ids_of("contact") == {"contact-active"}


def test_a_contact_refusal_is_reported_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator learns which contact Xero would not archive, and why."""
    Company.objects.create(
        name="[TEST] Stubborn Supplier",
        xero_contact_id="contact-stubborn",
        xero_last_modified="2026-08-08T00:00Z",
    )

    monkeypatch.setattr(
        f"{RESIDUE}.archive_contacts_in_xero",
        lambda _ids: ArchiveOutcome(
            archived=(), refused={"contact-stubborn": "Contact has outstanding transactions"}
        ),
    )

    output = _run_cleanup("--confirm")

    assert "[TEST] Stubborn Supplier: Contact has outstanding transactions" in output


def test_a_document_refusal_is_reported_by_number_and_does_not_stop_the_cleanup(
    monkeypatch: pytest.MonkeyPatch, office_staff: Staff
) -> None:
    """An invoice Xero will not delete must name itself and still let the rest finish."""
    company = Company.objects.create(name="[TEST] Company", xero_last_modified="2026-08-08T00:00Z")
    job = make_job(company, office_staff, name="[TEST] Job")
    invoice = make_invoice(company, job=job)

    class RefusingOrganisation(RecordingOrganisation):
        """Accepts everything except the invoice, which Xero will not reopen."""

        def delete_invoice(self, external_id: str) -> DocumentResult:
            return DocumentResult(
                success=False,
                external_id=external_id,
                validation_errors=["Invoice not of valid status for modification"],
            )

    monkeypatch.setattr(f"{RESIDUE}.get_provider", RefusingOrganisation)

    output = _run_cleanup("--confirm")

    assert f"Xero refused invoice {invoice.number}" in output
    assert "Invoice not of valid status for modification" in output
    # The local rows still go: the refusal is Xero's permanent answer about
    # that document, not a reason to leave the database dirty for every run
    # after this one.
    assert "Done." in output
    assert not Job.objects.filter(pk=job.pk).exists()


@pytest.fixture
def phone_storage_root(settings: SettingsWrapper, tmp_path: Path) -> Path:
    settings.PHONE_RECORDING_STORAGE_ROOT = str(tmp_path)
    return tmp_path


def _recorded_call(
    provider_id: str,
    *,
    description: str,
    company: Company | None = None,
) -> tuple[PhoneCallRecord, PhoneCallRecording]:
    """A call with a real archived file, built through the production store path."""
    call = make_call(provider_id, company=company, description=description)
    recording = make_recording(call, f"rec-{provider_id}", storage_path=None)
    store_recording_bytes(
        call=call,
        recording=recording,
        content=silent_wav(0.5),
        filename="e2e-call.wav",
        content_type="audio/wav",
    )
    recording.refresh_from_db()
    return call, recording


def test_confirm_deletes_e2e_phone_calls_with_their_files(phone_storage_root: Path) -> None:
    """A seeded call outlives its job and company (both SET_NULL), so it must be
    matched on its own marker or it sits in the Unmatched queue forever, with a
    stranded file behind it.
    """
    call, recording = _recorded_call("seeded", description=f"{TEST_DATA_PREFIX} seeded call")
    real_call, real_recording = _recorded_call("customer", description="Customer called back")
    seeded_file = phone_storage_root / str(recording.storage_path)
    real_file = phone_storage_root / str(real_recording.storage_path)

    output = _run_cleanup("--confirm")

    assert "Done." in output
    assert not PhoneCallRecord.objects.filter(pk=call.pk).exists()
    assert not PhoneCallRecording.objects.filter(pk=recording.pk).exists()
    assert not seeded_file.exists()
    assert PhoneCallRecord.objects.filter(pk=real_call.pk).exists()
    assert PhoneCallRecording.objects.filter(pk=real_recording.pk).exists()
    assert real_file.exists()


def test_dry_run_reports_phone_calls_without_deleting(phone_storage_root: Path) -> None:
    """An inspection names the E2E-seeded phone calls and leaves both row and file."""
    call, recording = _recorded_call("listed", description=f"{TEST_DATA_PREFIX} listed call")

    output = _run_cleanup()

    assert "E2E phone calls" in output
    assert str(call.description) in output
    assert "E2E phone recordings with a local file" in output
    assert recording.provider_recording_id in output
    assert PhoneCallRecord.objects.filter(pk=call.pk).exists()
    assert (phone_storage_root / str(recording.storage_path)).exists()


@pytest.mark.usefixtures("phone_storage_root")
def test_a_call_orphaned_by_set_null_is_still_deleted() -> None:
    """The description is the whole rule: a call whose company an earlier run
    removed has nothing else left to recognise it by.
    """
    call, _ = _recorded_call(
        "orphan", description=f"{TEST_DATA_PREFIX} orphaned call", company=None
    )

    _run_cleanup("--confirm")

    assert not PhoneCallRecord.objects.filter(pk=call.pk).exists()


def test_a_failed_cleanup_keeps_the_phone_call_row(
    phone_storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files go before the commit on purpose: a rollback leaves a row whose file
    is gone, which the download endpoint already answers with 404 and the next
    --confirm finishes. Files after the commit would orphan files no run can find.
    """
    call, recording = _recorded_call("rollback", description=f"{TEST_DATA_PREFIX} rollback call")
    stored_file = phone_storage_root / str(recording.storage_path)
    original_delete = Command._delete_queryset

    def delete_then_fail(self: Command, label: str, queryset: QuerySet[Model]) -> None:
        original_delete(self, label, queryset)
        if label == "E2E phone calls":
            raise RuntimeError("simulated cleanup failure")

    monkeypatch.setattr(Command, "_delete_queryset", delete_then_fail)

    with pytest.raises(RuntimeError, match="simulated cleanup failure"):
        _run_cleanup("--confirm")

    assert PhoneCallRecord.objects.filter(pk=call.pk).exists()
    assert not stored_file.exists()


def test_sweeps_test_prefixed_process_documents(office_staff: Staff) -> None:
    """v1's scroll spec leaked one permanent form per run into the incident
    list; the sweep is what makes the ported spec residue-free."""
    form = Form.objects.create(
        document_type="form",
        category=Form.Category.INCIDENT,
        title="[TEST] Tall Incident Form",
        form_schema={"fields": []},
    )
    FormEntry.objects.create(form=form, entry_date="2026-08-25", data={})
    # Acknowledgement has no queryset of its own in the command: it CASCADEs
    # from form, so deleting the form above is expected to take it too.
    acknowledgement = Acknowledgement.objects.create(staff=office_staff, form=form)
    keeper = Form.objects.create(
        document_type="form",
        category=Form.Category.SAFETY,
        title="Real form",
        form_schema={"fields": []},
    )
    call_command("e2e_cleanup", "--confirm")
    assert not Form.objects.filter(pk=form.pk).exists()
    assert not FormEntry.objects.exists()
    assert not Acknowledgement.objects.filter(pk=acknowledgement.pk).exists()
    assert Form.objects.filter(pk=keeper.pk).exists()
