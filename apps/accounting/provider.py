"""Accounting provider protocol — the interface every backend must implement.

ADR 0012: all accounting access goes through ``get_provider()``; SDK types
never leave the provider that owns them. The Protocol grows per-slice — it
declares only the operations a ported consumer actually calls, so an entry
here is a promise some v2 code exercises it.
"""

import datetime
from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from apps.company.models import Company

    from .types import (
        ContactResult,
        DocumentResult,
        DocumentTheme,
        InvoicePayload,
        NewPayrollEmployee,
        PayrollEmployeeRef,
        PayrollLeaveBalance,
        PayrollMirrorScope,
        PayrollSlip,
        PayRunRef,
        PayRunSyncResult,
        POPayload,
        QuotePayload,
        QuotePdfDocument,
        StaffWeekPosting,
        StaffWeekPostResult,
    )


class AccountingProvider(Protocol):
    """Interface that every accounting backend must implement.

    Each installation uses exactly one provider, resolved by
    ``registry.get_provider()`` from ``CompanyDefaults.accounting_provider``.
    """

    #: Human-readable backend name for error messages and logs (e.g. "Xero").
    provider_name: str

    def get_valid_token(self) -> Mapping[str, object] | None:
        """Return a valid auth token, refreshing if needed; None means not connected."""
        ...

    def disconnect(self) -> None:
        """Sever the connection: wipe stored token material."""
        ...

    def create_contact(self, company: "Company") -> "ContactResult":
        """Create the company as a contact in the accounting system."""
        ...

    def update_contact(self, company: "Company") -> "ContactResult":
        """Push the company's current details to its existing contact (upserts)."""
        ...

    def search_contact_by_name(self, name: str) -> "ContactResult | None":
        """Find a contact by exact name; None when the name is unknown."""
        ...

    def list_document_themes(self) -> "list[DocumentTheme]":
        """Return the provider's document presentation themes, default first."""
        ...

    def create_invoice(self, payload: "InvoicePayload") -> "DocumentResult":
        """Create a sales invoice; the result carries id/number/raw payload."""
        ...

    def delete_invoice(self, external_id: str) -> "DocumentResult":
        """Void/delete the invoice identified by ``external_id``."""
        ...

    def create_quote(self, payload: "QuotePayload") -> "DocumentResult":
        """Create a sales quote; the result carries id/number/raw payload."""
        ...

    def delete_quote(self, external_id: str) -> "DocumentResult":
        """Void/delete the quote identified by ``external_id``."""
        ...

    def download_quote_pdf(self, external_id: str) -> "QuotePdfDocument":
        """Render the quote to PDF on local disk; the caller owns the file.

        Raises rather than returning an error result: a missing PDF has no
        partial-success shape, and the one consumer (quote PDF inspection)
        needs the real cause.
        """
        ...

    def create_purchase_order(self, payload: "POPayload") -> "DocumentResult":
        """Create a purchase order."""
        ...

    def update_purchase_order(self, payload: "POPayload") -> "DocumentResult":
        """Update the purchase order named by ``payload.external_id``."""
        ...

    def delete_purchase_order(self, external_id: str) -> "DocumentResult":
        """Void/delete the purchase order identified by ``external_id``."""
        ...

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        """Attach a file to an invoice; best-effort, False on failure."""
        ...

    def add_history_note_to_invoice(self, invoice_external_id: str, note: str) -> bool:
        """Add a history note to an invoice; best-effort, False on failure."""
        ...

    def add_history_note_to_quote(self, quote_external_id: str, note: str) -> bool:
        """Add a history note to a quote; best-effort, False on failure."""
        ...

    def get_account_code(self, account_name: str) -> str:
        """Resolve an account name to its code; raises when unknown."""
        ...

    # --- Payroll ---------------------------------------------------------
    #
    # The weekly timesheets screen reaches payroll through here rather than
    # importing the integration: apps.xero sits ABOVE the domain apps in the
    # import contract, so apps.timesheet cannot call it directly.

    #: Opus: Whether this backend implements the payroll operations below.
    supports_payroll: bool

    # Opus: docstring rationale unratified (ADR 0051).
    def payroll_calendar_anchor_week(self) -> "tuple[datetime.date, datetime.date] | None":
        """Return the calendar's own first postable period, when it has no pay runs yet.

        Only reached in that one case; once any pay run exists the postable
        week is derived from the local mirror without touching the provider.
        """
        ...

    def create_pay_run(self, week_start_date: datetime.date) -> "PayRunRef":
        """Create a Draft pay run for the week and mirror it locally."""
        ...

    def refresh_pay_runs(self) -> "PayRunSyncResult":
        """Re-sync the local pay-run mirror from the provider."""
        ...

    def payroll_connection_id(self) -> str:
        """Return the payroll organisation identifier for an async task argument."""
        ...

    def sync_payroll_mirror(self, connection_id: str, scope: "PayrollMirrorScope") -> None:
        """Refresh payroll through the provider's normal sync implementation."""
        ...

    def week_posting_status(self, week_start_date: datetime.date) -> "list[StaffWeekPosting]":
        """Report what the provider currently holds for each staff member's week."""
        ...

    # Opus: docstring rationale unratified (ADR 0051).
    def post_payroll_week(
        self,
        connection_id: str,
        staff_ids: "Sequence[UUID]",
        week_start_date: datetime.date,
    ) -> "Iterator[StaffWeekPostResult]":
        """Post a week of hours for the given staff, yielding each one's result.

        A generator so the caller can report progress as it goes; the
        provider owns the order of operations, which is load-bearing and
        provider-specific (ADR 0007). Preflight failures raise before the
        first result is yielded, so nothing is half-posted by a bad
        configuration.

        ``connection_id`` is the organisation the run was dispatched for, and
        the provider REFUSES when it is no longer the connected one. ADR 0024
        makes the tenant an explicit argument; carrying it without checking it
        left the mirror sync and the posting itself free to target different
        organisations.
        """
        ...

    # --- Payroll employees -----------------------------------------------
    #
    # apps.timesheet owns the Staff-to-employee matching and reaches the
    # provider through here: apps.xero sits ABOVE the domain apps in the
    # import contract, so it cannot be called directly.

    def list_payroll_employees(self) -> "list[PayrollEmployeeRef]":
        """Every payroll employee the connected organisation holds."""
        ...

    def get_payroll_leave_balances(self, employee_external_id: str) -> "list[PayrollLeaveBalance]":
        """Return the employee's current leave balances from the provider."""
        ...

    def get_pay_slips_for_week(self, week_start_date: "datetime.date") -> "list[PayrollSlip]":
        """Every pay slip the provider computed for the week's pay run.

        Read live from the run rather than from the synced mirror, so the
        reconciliation can answer in the minutes after posting — when a mistake
        is still cheap to fix — instead of waiting for the run to be Posted and
        a sync to have mirrored it.

        Driven by the provider's slips rather than our staff list, which is the
        whole point: an employee the provider pays that we posted nothing for
        can only appear if the provider's side is the one being iterated.
        """
        ...

    def create_payroll_employee(self, spec: "NewPayrollEmployee") -> "PayrollEmployeeRef":
        """Create a payroll employee, fully set up for a pay run.

        "Fully set up" is the contract, not a courtesy: an employee without
        employment, salary, working pattern, tax details, a bank account and
        leave entitlements is one Xero refuses to include in a pay run, so a
        partial create would satisfy this call and still leave payroll broken.
        """
        ...

    def update_payroll_employee_name(
        self, external_id: str, first_name: str, last_name: str
    ) -> None:
        """Push the local name onto an already-existing payroll employee."""
        ...
