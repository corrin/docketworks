"""Wire contracts for leave management and administration."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field, StringConstraints

from apps.core.schemas import NullableText, Quantity, ResponseSchema


class LeaveDayInput(Schema):
    """Operator-selected hours for one proposed date."""

    date: date
    hours: Annotated[Quantity, Field(gt=0)]


class LeavePreviewRequest(Schema):
    """Employee and inclusive range to preview."""

    staff_id: UUID
    start_date: date
    end_date: date


class LeavePreviewDayOut(ResponseSchema):
    """Scheduled date availability."""

    date: date
    scheduled_hours: Quantity
    hours: Quantity
    available: bool
    reason: str | None


class LeavePreviewOut(ResponseSchema):
    """One employee's range preview."""

    staff_id: str
    staff_name: str
    start_date: date
    end_date: date
    days: list[LeavePreviewDayOut]
    available_hours: Quantity


class LeaveRequestWrite(Schema):
    """Create a first-class leave request."""

    staff_id: UUID
    leave_type_code: str
    start_date: date
    end_date: date
    note: NullableText = None
    days: Annotated[list[LeaveDayInput], Field(min_length=1)]


class LeaveRequestUpdate(Schema):
    """Replace an existing leave request."""

    leave_type_code: str
    start_date: date
    end_date: date
    note: NullableText = None
    days: Annotated[list[LeaveDayInput], Field(min_length=1)]


class LeaveDayOut(ResponseSchema):
    """Persisted leave day and payroll-line identity."""

    id: str
    date: date
    hours: Quantity
    cost_line_id: str


class LeaveRequestOut(ResponseSchema):
    """Persisted leave request."""

    id: str
    staff_id: str
    staff_name: str
    leave_type_code: str
    leave_type_name: str
    start_date: date
    end_date: date
    note: str | None
    source: str
    batch_id: str | None
    total_hours: Quantity
    days: list[LeaveDayOut]
    created_at: datetime


class LeaveSaveOut(ResponseSchema):
    """Saved request and any conflicts skipped at commit."""

    request: LeaveRequestOut
    skipped_days: list[LeavePreviewDayOut]


class LeaveSummaryOut(ResponseSchema):
    """Quick figures over the filtered request set."""

    away_today: int
    upcoming_requests: int
    upcoming_hours: Quantity


class LeaveListOut(ResponseSchema):
    """Current or history leave listing."""

    scope: Literal["current", "history"]
    requests: list[LeaveRequestOut]
    summary: LeaveSummaryOut


class LeaveBalanceOut(ResponseSchema):
    """Live provider leave balance."""

    balance: Quantity
    unit: str
    name: str


class OfficeClosureWrite(Schema):
    """Inclusive closure range and optional note."""

    start_date: date
    end_date: date
    note: NullableText = None


class OfficeClosurePreviewOut(ResponseSchema):
    """Staff and hours affected by an office closure."""

    start_date: date
    end_date: date
    staff: list[LeavePreviewOut]
    available_staff: int
    available_hours: Quantity


class OfficeClosureOut(ResponseSchema):
    """Batched requests created for an office closure."""

    batch_id: str
    requests: list[LeaveRequestOut]
    skipped_days: list[LeavePreviewDayOut]


#: Opus: A named union on the wire, not a bare string. The three surfaces are a
#: closed set the backend already enumerates, and publishing them as an enum is
#: what makes a frontend branch on "xero_computed" a compile error when the set
#: changes (ADR 0028) — the same shape SettingsFieldType uses.
type PostingSurfaceOut = Literal["timesheet", "leave_api", "xero_computed"]


class LeaveTypeOut(ResponseSchema):
    """Fixed Docketworks type and its effective mapping."""

    code: str
    display_name: str
    job_id: str | None
    job_name: str | None
    xero_pay_item_id: str | None
    xero_pay_item_name: str | None
    posting_surface: PostingSurfaceOut
    configured: bool


class LeaveSettingsOut(ResponseSchema):
    """Leave mapping administration data."""

    leave_types: list[LeaveTypeOut]


class LeaveTypeUpdate(Schema):
    """Editable fields for one fixed leave code.

    Fable: ``xero_pay_item_id`` is required-but-nullable, not optional: null is
    a statement, and it is the only truthful one for the ``xero_computed``
    surface, which has no Xero object to name. Requiring a UUID here made every
    save containing a public-holiday edit fail validation for a field the row
    cannot have, and the atomic batch took the other rows down with it. The
    service still refuses the two dishonest combinations (a pay item on
    ``xero_computed``, null on a surface that posts).
    """

    code: str
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    job_id: UUID
    xero_pay_item_id: UUID | None


class LeaveSettingsUpdate(Schema):
    """Every mapping the settings page changed, saved as one transaction."""

    leave_types: Annotated[list[LeaveTypeUpdate], Field(min_length=1)]
