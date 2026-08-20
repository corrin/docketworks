"""Read-only Xero provider: real reads and auth, suppressed writes.

Selected by the registry when ``settings.XERO_READONLY`` is true (E2E/test
backends only). Every write logs a warning and returns a well-formed fake
result so callers — the company-create flow today, document managers when
they port — behave exactly as with real Xero, without anything reaching the
Xero tenant. Suppressed writes are not errors: nothing here persists an
AppError.
"""

import logging
import uuid
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from apps.accounting.types import (
    ContactResult,
    DocumentLineItem,
    DocumentResult,
    InvoicePayload,
    NewPayrollEmployee,
    PayrollEmployeeRef,
    PayrollMirrorScope,
    PayRunSyncResult,
    POPayload,
    QuotePayload,
    QuotePdfDocument,
    StaffWeekPostResult,
)
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine
from apps.xero import payroll_push
from apps.xero.payroll_leave import require_pay_item
from apps.xero.provider import XeroAccountingProvider

if TYPE_CHECKING:
    from apps.company.models import Company

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


def _fake_id() -> str:
    return str(uuid.uuid4())


def _log_suppressed(operation: str, detail: str) -> None:
    logger.warning("XERO_READONLY: suppressed Xero write %s — %s", operation, detail)


def _fake_totals(line_items: list[DocumentLineItem]) -> tuple[str, str, str]:
    """Cosmetic GST-exclusive totals for stubbed documents (local display only)."""
    sub_total = sum((li.quantity * li.unit_amount for li in line_items), Decimal("0")).quantize(
        _CENT
    )
    tax = (sub_total * CompanyDefaults.get_solo().gst_rate).quantize(_CENT)
    total = sub_total + tax
    return str(sub_total), str(tax), str(total)


class XeroReadOnlyProvider(XeroAccountingProvider):
    """Xero provider variant whose write operations are no-ops.

    Reads, auth, and token refresh inherit unchanged from
    ``XeroAccountingProvider``.
    """

    # --- Contacts ---

    def create_contact(self, company: "Company") -> ContactResult:
        """Assign a synthetic contact id without touching the tenant."""
        if not company.validate_for_xero():
            return ContactResult(
                success=False, error=f"Company {company.id} failed Xero validation"
            )
        # Mirror contacts.create_company_contact_in_xero's side effect: callers
        # (and the frontend Xero badge) read company.xero_contact_id.
        company.xero_contact_id = _fake_id()
        company.save(update_fields=["xero_contact_id"])
        _log_suppressed("create_contact", f"company {company.id} ({company.name})")
        return ContactResult(success=True, external_id=company.xero_contact_id, name=company.name)

    def update_contact(self, company: "Company") -> ContactResult:
        """Suppress the push; upsert a synthetic id when the company has none."""
        # The live provider validates every update (sync_company_to_xero);
        # skipping it here would make readonly tests pass an update
        # production rejects.
        if not company.validate_for_xero():
            return ContactResult(
                success=False, error=f"Company {company.id} failed Xero validation"
            )
        if not company.xero_contact_id:
            # Mirror contacts.sync_company_to_xero: updating a company that has
            # no contact ID is an upsert — it creates the contact and assigns
            # a fresh ID rather than succeeding with a missing external_id.
            return self.create_contact(company)
        _log_suppressed("update_contact", f"company {company.id} ({company.name})")
        return ContactResult(success=True, external_id=company.xero_contact_id, name=company.name)

    # --- Documents ---

    def create_invoice(self, payload: InvoicePayload) -> DocumentResult:
        """Fabricate a created invoice; nothing reaches the tenant.

        The raw_response mirrors process_xero_data's underscore-prefixed keys —
        the invoice manager reads ``_sub_total``/``_total_tax``/``_total``/
        ``_amount_due`` from it to populate the local Invoice row, so the
        E2E balance assertions settle exactly as they would against real Xero.
        """
        fake = _fake_id()
        number = f"INV-E2E-{fake[:8].upper()}"
        sub_total, tax, total = _fake_totals(payload.line_items)
        _log_suppressed("create_invoice", f"{number} for {payload.company_name}")
        return DocumentResult(
            success=True,
            external_id=fake,
            number=number,
            online_url=f"https://go.xero.com/app/invoicing/edit/{fake}",
            raw_response={
                "_invoice_id": fake,
                "_invoice_number": number,
                "_sub_total": sub_total,
                "_total_tax": tax,
                "_total": total,
                "_amount_due": total,
                "_contact": {"_name": payload.company_name},
                "_e2e_stub": True,
            },
        )

    def delete_invoice(self, external_id: str) -> DocumentResult:
        """Suppress the delete.

        No pre-read: the ID may be a stub that never existed in Xero, so the
        live path's get_invoice would 404.
        """
        _log_suppressed("delete_invoice", external_id)
        return DocumentResult(success=True, external_id=external_id)

    # --- Quotes ---

    def create_quote(self, payload: QuotePayload) -> DocumentResult:
        """Fabricate a created quote; nothing reaches the tenant.

        The raw_response mirrors process_xero_data's underscore-prefixed keys —
        the quote manager reads ``_sub_total``/``_total`` from it to populate
        the local Quote row.
        """
        fake = _fake_id()
        number = f"QU-E2E-{fake[:8].upper()}"
        sub_total, _tax, total = _fake_totals(payload.line_items)
        _log_suppressed("create_quote", f"{number} for {payload.company_name}")
        return DocumentResult(
            success=True,
            external_id=fake,
            number=number,
            online_url=f"https://go.xero.com/app/quotes/edit/{fake}",
            raw_response={
                "_quote_id": fake,
                "_quote_number": number,
                "_sub_total": sub_total,
                "_total": total,
                "_contact": {"_name": payload.company_name},
                "_e2e_stub": True,
            },
        )

    def delete_quote(self, external_id: str) -> DocumentResult:
        """Suppress the delete.

        No pre-read: the ID may be a stub that never existed in Xero, so the
        live path's get_quote would 404.
        """
        _log_suppressed("delete_quote", external_id)
        return DocumentResult(success=True, external_id=external_id)

    def download_quote_pdf(self, external_id: str) -> QuotePdfDocument:
        """Refuse: a native Xero-rendered PDF cannot be fabricated.

        Raising beats returning a fake path — the one consumer asserts on the
        PDF's rendered text, and a fabricated file would make that assertion
        pass against nothing.
        """
        raise RuntimeError(
            f"XERO_READONLY: a native Xero quote PDF cannot be downloaded ({external_id})"
        )

    # --- Purchase orders ---

    def _create_or_update_purchase_order(
        self,
        payload: POPayload,  # noqa: ARG002 -- signature must shadow the live helper exactly
    ) -> DocumentResult:
        # Tripwire, not a silent no-op: a new public PO method that forgets
        # its readonly override would otherwise write to the live tenant path.
        raise RuntimeError(
            "XERO_READONLY: real Xero PO helper reached — a write override is missing"
        )

    @staticmethod
    def _stub_purchase_order(payload: POPayload, external_id: str) -> DocumentResult:
        _log_suppressed(
            "create_or_update_purchase_order", f"{payload.po_number} for {payload.supplier_name}"
        )
        return DocumentResult(
            success=True,
            external_id=external_id,
            number=payload.po_number,
            online_url=(f"https://go.xero.com/Accounts/Payable/PurchaseOrders/Edit/{external_id}/"),
            # Empty line_items: no fabricated per-line ids, so the manager's
            # xero_line_item_id backfill is a no-op under readonly.
            raw_response={"line_items": [], "_e2e_stub": True},
        )

    def create_purchase_order(self, payload: POPayload) -> DocumentResult:
        """Fabricate a created purchase order; nothing reaches the tenant."""
        return self._stub_purchase_order(payload, _fake_id())

    def update_purchase_order(self, payload: POPayload) -> DocumentResult:
        """Suppress the update; echo the existing external id."""
        if not payload.external_id:
            raise ValueError("Cannot update purchase order without external_id")
        return self._stub_purchase_order(payload, payload.external_id)

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        """Suppress the delete; no pre-read (the ID may be a stub)."""
        _log_suppressed("delete_purchase_order", external_id)
        return DocumentResult(success=True, external_id=external_id)

    # --- Attachments ---

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        """Suppress the upload; report success as the live path would."""
        _log_suppressed(
            "attach_file_to_invoice",
            f"{file_name} ({len(content)} bytes) on invoice {invoice_external_id}",
        )
        return True

    # --- History notes ---

    def _add_history_note(
        self,
        document_kind: str,  # noqa: ARG002 -- signature must shadow the live helper exactly
        document_id: str,  # noqa: ARG002
        note: str,  # noqa: ARG002
    ) -> bool:
        # Tripwire, not a silent no-op: a new public note method that forgets
        # its readonly override would otherwise write to the live tenant path.
        raise RuntimeError(
            "XERO_READONLY: real Xero history helper reached — a write override is missing"
        )

    def add_history_note_to_invoice(
        self,
        invoice_external_id: str,
        note: str,  # noqa: ARG002 -- suppressed write; the note goes nowhere by design
    ) -> bool:
        """Suppress the note; report success as the live path would."""
        _log_suppressed("add_history_note_to_invoice", invoice_external_id)
        return True

    def add_history_note_to_quote(
        self,
        quote_external_id: str,
        note: str,  # noqa: ARG002 -- suppressed write; the note goes nowhere by design
    ) -> bool:
        """Suppress the note; report success as the live path would."""
        _log_suppressed("add_history_note_to_quote", quote_external_id)
        return True

    # --- Payroll ---------------------------------------------------------
    #
    # Opus: Reads are real; writes are suppressed. Only the SUPPRESSED members are
    # listed — the reads (the calendar anchor, the week posting status, the
    # connection id) are inherited unchanged, because an override whose body is
    # identical to the one it overrides restates intent in a docstring and
    # nothing else (ADR 0045).
    #
    # Payroll writes matter more than most: a suppressed post must still look
    # like a post to the caller, or the weekly screen's progress and result UI
    # cannot be exercised at all under XERO_READONLY.

    supports_payroll = True

    @staticmethod
    def refresh_pay_runs() -> PayRunSyncResult:
        """Report a mirror refresh that never ran."""
        _log_suppressed("refresh_pay_runs", "no pay runs fetched")
        return PayRunSyncResult(fetched=0, created=0, updated=0)

    @staticmethod
    def sync_payroll_mirror(connection_id: str, scope: PayrollMirrorScope) -> None:
        """Suppress the immediate payroll mirror refresh in read-only mode."""
        _log_suppressed("sync_payroll_mirror", f"{connection_id}:{scope.value}")

    @staticmethod
    def post_payroll_week(
        connection_id: str, staff_ids: Sequence[UUID], week_start_date: date
    ) -> Iterator[StaffWeekPostResult]:
        """Report every staff week as posted without touching Xero.

        Opus: The hour figures come from the same CostLines a real post would read,
        so the screen shows true numbers against a fake timesheet id.
        """
        # Opus: The dispatched tenant is not checked here because nothing is written;
        # the real provider refuses on a mismatch (payroll_push.require_dispatched_tenant).
        del connection_id
        _log_suppressed(
            "post_payroll_week", f"{len(staff_ids)} staff, week {week_start_date.isoformat()}"
        )
        return _suppressed_week_posts(staff_ids, week_start_date)

    # --- Payroll employees ---
    #
    # The only writes here that REFUSE rather than fake. Every other override
    # fabricates a result because nothing durable depends on it being real;
    # the employee id, by contrast, is written straight onto Staff.xero_user_id
    # and is what payroll posting later addresses. A fabricated one produces a
    # database that looks linked and cannot pay anybody — the exact corruption
    # operator_guards.assert_xero_writes_enabled exists to prevent.
    # list_payroll_employees is a read and inherits unchanged.

    @staticmethod
    def create_payroll_employee(spec: NewPayrollEmployee) -> PayrollEmployeeRef:
        """Refuse: a fabricated employee id would be persisted onto Staff."""
        raise RuntimeError(
            "XERO_READONLY: refusing to create a payroll employee for "
            f"{spec.email}. A suppressed create returns an id that does not "
            "exist in Xero, and the caller saves it onto Staff.xero_user_id. "
            "Unset XERO_READONLY for this process and run against a "
            "non-production organisation."
        )

    @staticmethod
    def update_payroll_employee_name(external_id: str, first_name: str, last_name: str) -> None:
        """Refuse: the local name would silently diverge from the organisation."""
        raise RuntimeError(
            f"XERO_READONLY: refusing to rename payroll employee {external_id} "
            f"to {first_name} {last_name}. Reporting success would leave the "
            "mirror claiming a name the organisation does not hold."
        )


def _suppressed_week_posts(
    staff_ids: "Sequence[UUID]", week_start_date: date
) -> "Iterator[StaffWeekPostResult]":
    """Yield the result a real post would report per staff member, reading real hours.

    Opus: Split by the same classifier the real provider posts through, not summed
    into ``work_hours``. Every hour landed in the work bucket, so a week
    containing any leave reported figures no run could produce — while the
    docstring claimed "the screen shows true numbers". A read-only provider that
    lies about the shape of a result is worse than one that refuses, because the
    screen it feeds is exactly where an operator checks what a post would do.

    Fable: The lines come from ``payroll_push._week_time_lines`` — the query the
    real run reads — not a local restatement of it, and the salary/hourly split
    mirrors ``payroll_push._post_one_staff_week`` field for field: a salaried
    staff member is a skip in ``posting_mode="salary"`` with no timesheet id,
    because the real provider never posts them a timesheet.
    ``salary_timesheet_removed`` stays False rather than asking Xero whether a
    sheet exists: a suppressed post removes nothing, and the read would be this
    module's only payroll call to the tenant.
    """
    # Opus: Call-time import: these are loaded through the app registry, and this
    # module is imported at app-ready.
    from apps.accounts.models import Staff  # noqa: PLC0415
    from apps.timesheet.services import hour_categories  # noqa: PLC0415

    week = payroll_push._WeekWindow.of(week_start_date)
    catalogue = hour_categories.LeaveCatalogue.load()
    lines_by_staff: dict[str, list[CostLine]] = defaultdict(list)
    for line in payroll_push._week_time_lines(week, staff_ids):
        lines_by_staff[str(line.staff_id)].append(line)

    week_end = week.end
    for staff in Staff.objects.filter(id__in=list(staff_ids)):
        staff_lines = lines_by_staff.get(str(staff.id), [])
        # Fable: The same two guards the real provider answers with, in the
        # same order — the fidelity claim below is only true if a suppressed
        # week reports the departures and unlinked employees a real one would.
        if not staff.is_active_between(week.start, week_end):
            yield payroll_push._skip_result(
                staff, "Not employed during this week", bool(staff_lines)
            )
            continue
        if not staff.xero_user_id:
            yield payroll_push._failure_result(
                staff,
                f"{staff.get_display_full_name()} is not linked to a Xero employee. "
                "Ask an administrator to link them, then post again.",
                bool(staff_lines),
            )
            continue
        split = payroll_push._split_by_surface(staff_lines, catalogue)
        leave_hours = sum((line.quantity for line in split.leave_api), Decimal("0"))
        if staff.pay_basis == "salary":
            yield StaffWeekPostResult(
                staff_id=str(staff.id),
                staff_name=staff.get_display_full_name(),
                success=True,
                skipped=True,
                reason=payroll_push.SALARY_SKIP_REASON,
                work_hours=sum((line.quantity for line in split.timesheet), Decimal("0")),
                leave_hours=leave_hours,
                has_entries=bool(staff_lines),
                posting_mode="salary",
                salary_timesheet_removed=False,
            )
            continue
        work_lines = [
            line for line in split.timesheet if require_pay_item(line).multiplier is not None
        ]
        other_leave_lines = [
            line for line in split.timesheet if require_pay_item(line).multiplier is None
        ]
        yield StaffWeekPostResult(
            staff_id=str(staff.id),
            staff_name=staff.get_display_full_name(),
            success=True,
            timesheet_id=_fake_id(),
            entries_posted=len(staff_lines),
            work_hours=sum((line.quantity for line in work_lines), Decimal("0")),
            other_leave_hours=sum((line.quantity for line in other_leave_lines), Decimal("0")),
            leave_hours=leave_hours,
            has_entries=bool(staff_lines),
        )
