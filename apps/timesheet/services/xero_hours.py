"""Xero payroll hours by staff-week, read from the local pay-run mirror.

Shared by the timesheet repair commands (``create_overtime_entries``,
``reclassify_overtime_entries``): they compare what Xero actually paid against
what the local time CostLines record, per staff member per Monday-aligned week.

This is the raw_json flow that the payroll reconciliation service
(``apps/accounting/services/payroll_reconciliation_service.py``) deliberately
does NOT consolidate: reconciliation reads the extracted model fields
(``timesheet_hours``/``leave_hours``), which cannot split overtime from
ordinary time or break leave down by type; this module reads the slips' raw
earnings lines, which can.

Layer contract: ``XeroPayRun``/``XeroPaySlip`` live in ``apps.xero``, above the
domain apps, so they are reached through Django's app registry behind
protocols — the pattern ``apps/timesheet/services/payroll_service.py`` uses.
"""

from collections.abc import Iterable, Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol, TypedDict, cast
from uuid import UUID

from django.db.models import Sum

from apps.accounts.models import Staff
from apps.core.xero_registry import xero_model_manager
from apps.job.models.costing import CostLine

# Earliest week to process (pre-Xero payroll data is unreliable).
CUTOFF_DATE = date(2025, 8, 11)

# Mapping from Xero leave display-name prefix to the local leave job name.
LEAVE_TYPE_MAP = {
    "Sick Leave": "Sick Leave",
    "Annual Leave": "Annual Leave",
    "Unpaid Leave": "Unpaid Leave",
    "Bereavement Leave": "Bereavement Leave",
    "Stand Down Leave": "Bereavement Leave",  # logged as bereavement locally
    "Alternative Holidays": "Annual Leave",
    "Holiday Pay": "Annual Leave",
}

# The special jobs that hold leave time entries.
LEAVE_JOB_NAMES = {
    "Annual Leave",
    "Sick Leave",
    "Bereavement Leave",
    "Unpaid Leave",
    "Statutory holiday",
}


# ---------------------------------------------------------------------------
# Structural views of the apps.xero models (layer contract: no direct import)
# ---------------------------------------------------------------------------


class _PaySlipRow(Protocol):
    """The XeroPaySlip surface the hours extraction reads."""

    @property
    def xero_employee_id(self) -> UUID:
        """Xero's employee id — joined to ``Staff.xero_user_id``."""

    @property
    def employee_name(self) -> str | None:
        """Denormalised employee name, for reporting."""

    @property
    def raw_json(self) -> dict[str, object]:
        """The unmodified Xero pay-slip payload (earnings line detail)."""


class _PaySlipSet(Protocol):
    """The related-manager surface for a pay run's slips."""

    def all(self) -> Iterable[_PaySlipRow]:
        """Return the pay run's slips (prefetched upstream)."""


class _PayRunRow(Protocol):
    """The XeroPayRun surface the hours extraction reads."""

    @property
    def period_start_date(self) -> date:
        """First day of the pay period — a Monday on the weekly calendar."""

    @property
    def pay_slips(self) -> _PaySlipSet:
        """The pay run's slips."""


class _PayRunQuery(Protocol):
    """The queryset surface the hours extraction needs."""

    def prefetch_related(self, *names: str) -> "_PayRunQuery":
        """Return the rows with the named relations prefetched."""

    def order_by(self, *fields: str) -> "_PayRunQuery":
        """Return the rows re-ordered by the given fields."""

    def __iter__(self) -> Iterator[_PayRunRow]:
        """Iterate the matched rows."""


class _PayRunMirror(Protocol):
    """The manager surface the hours extraction needs off XeroPayRun."""

    def filter(self, **kwargs: object) -> _PayRunQuery:
        """Return the mirror rows matching the given lookups."""


def _pay_run_mirror() -> _PayRunMirror:
    """Narrow the shared xero-registry seam to this module's protocol."""
    return cast("_PayRunMirror", xero_model_manager("XeroPayRun"))


# ---------------------------------------------------------------------------
# Result contracts
# ---------------------------------------------------------------------------


class XeroWeekRow(TypedDict):
    """One staff member's Xero payroll hours for one Monday-aligned week."""

    week_start: date
    xero_employee_id: str
    employee_name: str | None
    ordinary_hrs: Decimal
    ot_hrs: Decimal
    leave_hrs: Decimal
    leave_by_type: dict[str, Decimal]
    ordinary_rate: Decimal
    ot_rate: Decimal


class JmWeekHours(TypedDict):
    """One staff member's local (CostLine) hours for one week."""

    jm_total: Decimal
    jm_ot: Decimal
    jm_leave_by_type: dict[str, Decimal]


# ---------------------------------------------------------------------------
# raw_json boundary validation
# ---------------------------------------------------------------------------


def _extract_leave_type(display_name: str) -> str:
    """Map a Xero leave display name like 'Sick Leave (22 Sep 2025)' to a job name."""
    # Strip the date suffix in parentheses; prefix-match so variants like
    # "Annual Leave - Cash Up" still resolve.
    base = display_name.partition("(")[0].strip()
    for prefix, job_name in LEAVE_TYPE_MAP.items():
        if base.startswith(prefix):
            return job_name
    # v1 silently defaulted unknown leave lines to "Sick Leave", misfiling
    # them; an unmapped Xero leave name is a data question for the operator,
    # so it raises instead (ADR 0015).
    raise ValueError(
        f"Unrecognised Xero leave display name: '{display_name}'. Extend LEAVE_TYPE_MAP."
    )


def _earnings_lines(raw: dict[str, object], key: str) -> list[dict[str, object]]:
    """Return one earnings-line list from a slip payload, validated at the boundary."""
    lines = raw.get(key)
    if lines is None:
        return []
    if not isinstance(lines, list):
        raise TypeError(f"Pay slip raw_json['{key}'] is not a list: {lines!r}")
    for line in lines:
        if not isinstance(line, dict):
            raise TypeError(f"Pay slip raw_json['{key}'] entry is not an object: {line!r}")
    return cast("list[dict[str, object]]", lines)


def _line_decimal(line: dict[str, object], key: str) -> Decimal:
    """Read a numeric earnings-line field; Xero serialises absent amounts as null."""
    value = line.get(key)
    if value is None:
        return Decimal("0")
    if not isinstance(value, str | int | float | Decimal):
        raise TypeError(f"Earnings line field '{key}' is not numeric: {value!r}")
    return Decimal(str(value))


def _line_display_name(line: dict[str, object]) -> str:
    """Read an earnings line's display name; absent means unnamed, not an error."""
    value = line.get("_display_name")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"Earnings line '_display_name' is not a string: {value!r}")
    return value


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def _slip_week_row(week_start: date, slip: _PaySlipRow) -> XeroWeekRow:
    """Extract one slip's hours breakdown from its raw earnings lines."""
    raw = slip.raw_json or {}

    ordinary_hrs = Decimal("0")
    ot_hrs = Decimal("0")
    ordinary_rate = Decimal("0")
    ot_rate = Decimal("0")

    for line in _earnings_lines(raw, "_timesheet_earnings_lines"):
        display = _line_display_name(line)
        units = _line_decimal(line, "_number_of_units")
        rate = _line_decimal(line, "_rate_per_unit")
        if "half" in display.lower():
            ot_hrs += units
            ot_rate = rate
        elif "Ordinary" in display:
            ordinary_hrs += units
            ordinary_rate = rate
        else:
            # Matching the leave path's refusal (ADR 0015): a silently
            # dropped line understates xero_total, so the repair commands
            # compute wrong headroom/ot_gap for that staff-week — worse than
            # stopping, because the corruption is invisible.
            raise ValueError(
                f"Unrecognised Xero timesheet earnings display name: '{display}'. "
                "Extend the ordinary/overtime classification in _slip_week_row."
            )

    leave_hrs = Decimal("0")
    leave_by_type: dict[str, Decimal] = {}
    for line in _earnings_lines(raw, "_leave_earnings_lines"):
        units = _line_decimal(line, "_number_of_units")
        leave_hrs += units
        leave_type = _extract_leave_type(_line_display_name(line))
        leave_by_type[leave_type] = leave_by_type.get(leave_type, Decimal("0")) + units

    return XeroWeekRow(
        week_start=week_start,
        xero_employee_id=str(slip.xero_employee_id),
        employee_name=slip.employee_name,
        ordinary_hrs=ordinary_hrs,
        ot_hrs=ot_hrs,
        leave_hrs=leave_hrs,
        leave_by_type=leave_by_type,
        ordinary_rate=ordinary_rate,
        ot_rate=ot_rate,
    )


def get_xero_hours_by_staff_week() -> list[XeroWeekRow]:
    """Return Xero payroll hours per staff per week from posted pay runs."""
    rows: list[XeroWeekRow] = []
    posted_runs = (
        _pay_run_mirror()
        .filter(pay_run_status="Posted")
        .prefetch_related("pay_slips")
        .order_by("period_start_date")
    )
    for pay_run in posted_runs:
        # The period IS the week: the payroll calendar is Monday-anchored and
        # payroll_setup fails setup if Xero does not honour it. This used to
        # add a day first, compensating for a belief that periods start on
        # Sunday — idempotent under a Monday anchor, so harmless and invisible.
        monday = pay_run.period_start_date
        if monday < CUTOFF_DATE:
            continue
        for slip in pay_run.pay_slips.all():
            rows.append(_slip_week_row(monday, slip))
    return rows


def get_jm_hours_for_staff_week(staff_id: str, week_start: date) -> JmWeekHours:
    """Return local CostLine hours for one staff member for one week."""
    week_end = week_start + timedelta(days=6)

    jm_lines = CostLine.objects.filter(
        kind="time",
        cost_set__kind="actual",
        accounting_date__gte=week_start,
        accounting_date__lte=week_end,
        staff_id=staff_id,
    )

    jm_total = jm_lines.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    jm_ot = jm_lines.filter(
        xero_pay_item__multiplier__gt=Decimal("1"),
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")

    jm_leave_by_type: dict[str, Decimal] = {}
    leave_lines = (
        jm_lines.filter(cost_set__job__name__in=LEAVE_JOB_NAMES)
        .values("cost_set__job__name")
        .annotate(total=Sum("quantity"))
    )
    for row in leave_lines:
        jm_leave_by_type[row["cost_set__job__name"]] = row["total"]

    return JmWeekHours(
        jm_total=jm_total,
        jm_ot=jm_ot,
        jm_leave_by_type=jm_leave_by_type,
    )


def build_staff_lookup() -> dict[str, Staff]:
    """Build a lookup from ``xero_user_id`` -> Staff for all staff with Xero ids."""
    return {
        staff.xero_user_id: staff
        for staff in Staff.objects.filter(xero_user_id__isnull=False)
        if staff.xero_user_id is not None
    }
