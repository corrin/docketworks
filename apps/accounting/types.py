"""Provider-agnostic data transfer types for the accounting abstraction layer.

Grown per-slice with the AccountingProvider Protocol (ADR 0012).
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from apps.core.errors import InvalidInputError


class NotAPayrollWeekError(InvalidInputError):
    """A week that does not start on a Monday, so it is not a payroll period.

    Opus: Its own type so the shared application boundary can tell it apart from
    every other failure. Catching plain ``ValueError`` around a payroll read reported a
    malformed Xero response as HTTP 400 — telling the operator they had sent a
    bad request when the vendor had sent bad data.
    """


def require_payroll_week_start(week_start_date: "datetime.date") -> "datetime.date":
    """Refuse a week that does not start on a Monday — the one implementation.

    Opus: Xero pay periods are Monday-anchored, and this rule was written out four
    times: once in ``payroll_push._WeekWindow.of`` and three times in
    ``payroll_service``. Four copies of a rule are four chances for one to
    drift, and they sit either side of a layer boundary, so neither side could
    call the other's. Both sides import this module, so it lives here.
    """
    if week_start_date.weekday() != 0:
        raise NotAPayrollWeekError("week_start_date must be a Monday")
    return week_start_date


@dataclass(frozen=True)
class DocumentTheme:
    """A selectable document presentation theme from an accounting provider."""

    external_id: str
    name: str
    is_default: bool


@dataclass(frozen=True)
class ContactResult:
    """Result of a contact operation."""

    success: bool
    external_id: str | None = None
    name: str | None = None
    error: str | None = None


@dataclass
class DocumentLineItem:
    """A single line item on an invoice, quote, or purchase order."""

    description: str
    quantity: Decimal
    unit_amount: Decimal
    account_code: str | None = None
    item_code: str | None = None


@dataclass
class InvoicePayload:
    """Data needed to create an invoice in any accounting system."""

    client_external_id: str
    company_name: str
    line_items: list[DocumentLineItem]
    date: "datetime.date"
    due_date: "datetime.date"
    document_theme_external_id: str
    currency_code: str = "NZD"
    reference: str | None = None
    url: str | None = None
    status: str = "DRAFT"
    line_amount_type: str = "Exclusive"


@dataclass
class QuotePayload:
    """Data needed to create a quote in any accounting system.

    ``terms`` is required, not defaulted: Xero does not apply its own quote
    terms default to API-created quotes, so an empty value here would ship a
    quote with no terms — the manager validates before building this.
    """

    client_external_id: str
    company_name: str
    line_items: list[DocumentLineItem]
    date: "datetime.date"
    expiry_date: "datetime.date"
    document_theme_external_id: str
    terms: str
    currency_code: str = "NZD"
    reference: str | None = None
    status: str = "DRAFT"
    line_amount_type: str = "Exclusive"


@dataclass(frozen=True)
class QuotePdfDocument:
    """A provider-rendered quote PDF on local disk. The caller owns the file."""

    external_id: str
    document_theme_external_id: str | None
    temporary_file_path: str


@dataclass
class POPayload:
    """Data needed to create/update a purchase order in any accounting system."""

    supplier_external_id: str
    supplier_name: str
    po_number: str
    line_items: list[DocumentLineItem]
    date: "datetime.date"
    status: str = "DRAFT"
    delivery_date: "datetime.date | None" = None
    reference: str | None = None
    external_id: str | None = None


@dataclass
class DocumentResult:
    """Result of a document operation (create/update/delete)."""

    success: bool
    external_id: str | None = None
    number: str | None = None
    online_url: str | None = None
    raw_response: dict[str, Any] | None = None
    error: str | None = None
    status_code: int | None = None
    validation_errors: list[str] = field(default_factory=list)


# --- Payroll -------------------------------------------------------------
#
# The weekly timesheets screen posts a week of hours to the provider's payroll
# surface. Everything below crosses the provider boundary as plain data so no
# SDK type reaches the domain layer (ADR 0012).


class PayrollMirrorScope(StrEnum):
    """The business moment selecting which payroll mirror entities to refresh.

    Opus: There is no BEFORE_POST member. Refreshing the pay-run mirror before a
    post is not a moment a caller chooses — it is a precondition of the posting
    function itself, which now establishes it rather than trusting whoever
    called it to have done so (ADR 0015: check the bad case where it matters,
    not upstream of it).
    """

    AFTER_POST = "after_post"
    AFTER_SETTLE = "after_settle"


@dataclass(frozen=True)
class PayRunRef:
    """A pay run as the domain layer sees it: identity, period, and status."""

    pay_run_id: str
    payroll_calendar_id: str
    period_start_date: "datetime.date"
    period_end_date: "datetime.date"
    payment_date: "datetime.date"
    pay_run_status: str
    pay_run_type: str


@dataclass(frozen=True)
class PayRunSyncResult:
    """What re-syncing the local pay-run mirror from the provider changed."""

    fetched: int
    created: int
    updated: int


#: Opus: How a staff member's week was posted. A named union, not a bare `str`:
#: this was declared as a two-member union in TypeScript and as `str` here, so
#: the wire contract was stricter than the type that produced it and only the
#: hand-written copy said so.
type PayrollPostingMode = Literal["timesheet", "salary"]


@dataclass(frozen=True)
class StaffWeekPostResult:
    """One staff member's week, after the provider posted it.

    Fable: The three hour figures follow ADR 0007's posting surfaces: work and
    rate-paid leave both travel through the Timesheets API but are reported
    separately, and ``leave_hours`` is what went through the Leave API — the
    only surface that debits a balance. A public holiday posts nowhere and so
    appears in none of them. ``skipped`` covers a staff member outside the
    week (joined after it, or left before it); such a member may still have
    entries, which ``has_entries`` reports so the operator can see hours that
    were deliberately not posted.
    """

    staff_id: str
    staff_name: str
    success: bool
    timesheet_id: str | None = None
    leave_ids: tuple[str, ...] = ()
    entries_posted: int = 0
    work_hours: Decimal = Decimal("0")
    other_leave_hours: Decimal = Decimal("0")
    leave_hours: Decimal = Decimal("0")
    skipped: bool = False
    reason: str | None = None
    has_entries: bool = False
    error: str | None = None
    posting_mode: PayrollPostingMode = "timesheet"
    salary_timesheet_removed: bool = False


@dataclass(frozen=True)
class StaffWeekPosting:
    """What the provider holds for one staff member's week, beside what we recorded.

    Opus: Read from the provider rather than a local flag: a local "posted" column
    can disagree with what the payroll system actually holds, and eventually
    will (ADR 0007).

    Both sides are carried, split the same way, because only the pair answers
    the operator's actual question — "did the hours land?". A posted figure
    alone cannot be judged without the recorded one to judge it against.

    The timesheet/leave split is not presentation. The two travel to Xero
    through different APIs (ADR 0007) and only the Leave API debits a leave
    balance, so they read back from different places. Comparing a combined
    total against the timesheet side alone reported a shortfall on every week
    containing leave.
    """

    staff_id: str
    posted: bool
    timesheet_status: str | None
    posted_timesheet_hours: Decimal
    posted_leave_hours: Decimal
    recorded_timesheet_hours: Decimal
    recorded_leave_hours: Decimal
    pay_basis: str | None = None

    @property
    def posted_hours(self) -> Decimal:
        """Everything Xero holds for the week, across both APIs."""
        return self.posted_timesheet_hours + self.posted_leave_hours

    @property
    def recorded_hours(self) -> Decimal:
        """Everything the timesheet holds that Xero should be holding too.

        Opus: NOT every hour recorded for the week. Public-holiday hours are
        deliberately absent from both sides: Xero computes that day from the
        employee's working pattern and Docketworks posts nothing for it, so
        including them here would report a shortfall on every week containing
        one (ADR 0007). This is the comparable total, which is what the two
        posted/recorded pairs beside it are for.
        """
        return self.recorded_timesheet_hours + self.recorded_leave_hours

    @property
    def matches(self) -> bool:
        """Whether Xero holds what we recorded, on both surfaces.

        Opus: Compared per surface rather than on the totals: an equal grand total
        can hide leave posted as worked time, which pays the same gross and
        silently fails to debit the leave balance.

        A timesheet must EXIST, even for a nil week. Without one Xero pays the
        employee's pay-template hours — typically a full week nobody worked
        (ADR 0007, which is why an empty week still posts an empty timesheet).
        Comparing only the four figures made the zero-recorded, no-timesheet
        case read as agreement: all four are zero, so the row was filtered out
        of the panel and counted among the staff Xero "matches". The one state
        that overpays was the one state reported as fine.
        """
        if self.pay_basis == "salary":
            return not self.posted and self.posted_leave_hours == self.recorded_leave_hours
        if not self.posted:
            return False
        return (
            self.posted_timesheet_hours == self.recorded_timesheet_hours
            and self.posted_leave_hours == self.recorded_leave_hours
        )


# --- Payroll employees -------------------------------------------------------


@dataclass(frozen=True)
class PayrollEmployeeRef:
    """A payroll employee as the matcher and the linker need to see one.

    ``job_title`` is carried because it is where the Staff UUID is stored, and
    that UUID is the only match key that survives a database restore intact.
    """

    external_id: str
    first_name: str
    last_name: str
    email: str | None
    job_title: str | None


@dataclass(frozen=True)
class PayrollLeaveBalance:
    """One provider leave balance, retaining its provider type identifier and unit."""

    leave_type_external_id: str
    name: str
    balance: Decimal
    unit: str


@dataclass(frozen=True)
class PayrollSlip:
    """One employee's pay slip as the provider computed it for a week.

    The provider's own arithmetic over the records IT holds, not a reading back
    of what we sent. That is what makes it worth reconciling against: every
    other comparison in the payroll path reads back through the modules that
    wrote, so a wrong belief about the provider's contract would be written and
    read the same wrong way and still agree with itself.

    ``employee_name`` is carried because a slip can belong to an employee this
    installation has no Staff row for — the case the reconciliation exists to
    surface, since the provider pays them whether or not we know about them.
    """

    employee_external_id: str
    employee_name: str | None
    timesheet_hours: Decimal
    leave_hours: Decimal
    gross_earnings: Decimal


@dataclass(frozen=True)
class PayrollAddress:
    """The employer address a payroll employee is registered against."""

    address_line1: str
    address_line2: str | None
    suburb: str | None
    city: str
    post_code: str
    country_name: str


@dataclass(frozen=True)
class NewPayrollEmployee:
    """Everything a provider needs to create one payroll employee.

    Deliberately free of provider identifiers. v1 made the caller look up the
    payroll-calendar id and the ordinary-earnings-rate id and pass them in a
    dict, which put Xero UUIDs in the domain layer; the provider resolves both
    itself from configuration it already owns.

    ``hours_per_week`` is keyed by lowercase weekday name, monday..sunday, and
    every day must be present — a partial pattern is a data defect, not a
    provider concern.
    """

    staff_id: UUID
    first_name: str
    last_name: str
    email: str
    job_title: str
    date_of_birth: "datetime.date"
    start_date: "datetime.date"
    end_date: "datetime.date | None"
    address: PayrollAddress
    hours_per_week: dict[str, float]
    hourly_rate: Decimal
    ird_number: str
    bank_account_number: str
