"""Payroll reconciliation: Xero pay runs vs JM time CostLines, week by week.

Weeks are Monday-aligned; the ``jm - xero`` sign convention
means a positive diff is JM claiming more than Xero paid.

A separate ``apps/timesheet/services/xero_hours.py`` flow
reads slip ``raw_json`` instead of the model fields; it is a later slice and is
deliberately NOT consolidated here — this module keeps the reconciliation
report's own semantics (``timesheet_hours`` + ``leave_hours`` model fields).

Layer contract: ``XeroPayRun``/``XeroPaySlip`` live in ``apps.xero``, above the
domain apps, so they are reached through Django's app registry behind protocols
— the pattern ``apps/timesheet/services/payroll_service.py`` uses.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol, TypedDict, cast
from uuid import UUID

from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults
from apps.core.xero_registry import xero_model_manager
from apps.job.models.costing import CostLine

ZERO = Decimal("0")
# A week whose |cost diff| exceeds this many dollars is flagged as a mismatch.
THRESHOLD = Decimal("0.50")


# ---------------------------------------------------------------------------
# Structural views of the apps.xero models (layer contract: no direct import)
# ---------------------------------------------------------------------------


class _PaySlipRow(Protocol):
    """The XeroPaySlip surface the reconciliation reads."""

    @property
    def xero_id(self) -> UUID:
        """Xero's id for the pay slip (error messages only)."""

    @property
    def xero_employee_id(self) -> UUID:
        """Xero's employee id — joined to ``Staff.xero_user_id``."""

    @property
    def employee_name(self) -> str | None:
        """Denormalised employee name, for slips with no matching Staff."""

    @property
    def gross_earnings(self) -> Decimal:
        """Gross pay before deductions."""

    @property
    def timesheet_hours(self) -> Decimal:
        """Hours from timesheet earnings lines (actual worked hours)."""

    @property
    def leave_hours(self) -> Decimal:
        """Hours from leave earnings lines (sick, annual, ...)."""


class _PaySlipSet(Protocol):
    """The related-manager surface for a pay run's slips."""

    def all(self) -> Iterable[_PaySlipRow]:
        """Return the pay run's slips (prefetched upstream)."""


class _PayRunRow(Protocol):
    """The XeroPayRun surface the reconciliation reads."""

    @property
    def period_start_date(self) -> date:
        """First day of the pay period (a Sunday on the weekly calendar)."""

    @property
    def period_end_date(self) -> date:
        """Last day of the pay period."""

    @property
    def payment_date(self) -> date:
        """The date staff are paid."""

    @property
    def pay_slips(self) -> _PaySlipSet:
        """The run's pay slips."""


class _PayRunQuery(Protocol):
    """The queryset surface the reconciliation needs."""

    def prefetch_related(self, *lookups: str) -> "_PayRunQuery":
        """Return the rows with the given relations prefetched."""

    def order_by(self, *fields: str) -> "_PayRunQuery":
        """Return the rows re-ordered by the given fields."""

    def __iter__(self) -> Iterator[_PayRunRow]:
        """Iterate the matched rows."""


class _PayRunMirror(Protocol):
    """The manager surface off the XeroPayRun model."""

    def filter(self, **kwargs: object) -> _PayRunQuery:
        """Return the mirror rows matching the given lookups."""


def _pay_run_mirror() -> _PayRunMirror:
    """Narrow the shared xero-registry seam to this module's protocol."""
    return cast("_PayRunMirror", xero_model_manager("XeroPayRun"))


# ---------------------------------------------------------------------------
# Published wire shapes.
# ---------------------------------------------------------------------------


class PayrollStaffWeekRow(TypedDict):
    """Per-staff row within a single reconciliation week."""

    name: str
    xero_hours: float
    xero_timesheet_hours: float
    xero_leave_hours: float
    xero_gross: float
    xero_rate: float
    jm_hours: float
    jm_cost: float
    jm_rate: float
    hours_diff: float
    cost_diff: float
    hours_cost_impact: float
    rate_cost_impact: float
    status: str


class PayrollWeekTotals(TypedDict):
    """Aggregate totals for a single reconciliation week."""

    xero_gross: float
    jm_cost: float
    diff: float
    xero_hours: float
    jm_hours: float


class PayrollWeek(TypedDict):
    """One week of reconciliation data (pay runs vs JM CostLines)."""

    week_start: str
    xero_period_start: str | None
    xero_period_end: str | None
    payment_date: str | None
    totals: PayrollWeekTotals
    mismatch_count: int
    staff: list[PayrollStaffWeekRow]


class PayrollStaffSummary(TypedDict):
    """Per-staff aggregate across all weeks in the reporting window."""

    name: str
    xero_hours: float
    xero_gross: float
    jm_hours: float
    jm_cost: float
    hours_diff: float
    cost_diff: float
    hours_cost_impact: float
    rate_cost_impact: float
    weeks_present: int
    weeks_with_mismatch: int


class PayrollHeatmapRow(TypedDict):
    """Single row in the heatmap grid (one week)."""

    week_start: str
    cells: dict[str, float | None]


class PayrollHeatmap(TypedDict):
    """Week x staff cost-difference heatmap."""

    staff_names: list[str]
    rows: list[PayrollHeatmapRow]


class PayrollGrandTotals(TypedDict):
    """Grand totals across all weeks in the reporting window."""

    xero_gross: float
    jm_cost: float
    diff: float
    diff_pct: float


class PayrollReconciliationData(TypedDict):
    """The whole report body."""

    weeks: list[PayrollWeek]
    staff_summaries: list[PayrollStaffSummary]
    heatmap: PayrollHeatmap
    grand_totals: PayrollGrandTotals


class AlignedDateRange(TypedDict):
    """Pay-period-aligned week boundaries for arbitrary input dates."""

    aligned_start: date
    aligned_end: date


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_reconciliation_data(start_date: date, end_date: date) -> PayrollReconciliationData:
    """Build the full payroll reconciliation report.

    Discovers weeks from both Xero pay runs and JM CostLines, then
    cross-compares. Weeks that exist only on one side are included with the
    missing side showing zeros / null dates. The start is floored to
    ``CompanyDefaults.xero_payroll_start_date`` — weeks before Xero payroll
    went live have nothing to reconcile against.
    """
    payroll_start = CompanyDefaults.get_solo().xero_payroll_start_date
    if payroll_start is not None:
        start_date = max(start_date, payroll_start)

    try:
        staff_map = _build_staff_xero_map()

        # Discover Xero weeks. Filter by overlap: Xero periods start on Sunday
        # while JM weeks are Monday-based, so requiring period_start >= start
        # would miss the first week when the caller passes an aligned Monday.
        pay_runs = (
            _pay_run_mirror()
            .filter(
                pay_run_status="Posted",
                period_end_date__gte=start_date,
                period_start_date__lte=end_date,
            )
            .prefetch_related("pay_slips")
            .order_by("period_start_date")
        )

        xero_weeks: defaultdict[date, list[_PayRunRow]] = defaultdict(list)
        for pay_run in pay_runs:
            monday = _get_monday(pay_run.period_start_date + timedelta(days=1))
            xero_weeks[monday].append(pay_run)

        # Discover JM weeks.
        jm_time_dates = (
            CostLine.objects.filter(
                kind="time",
                cost_set__kind="actual",
                accounting_date__gte=start_date,
                accounting_date__lte=end_date,
            )
            .values_list("accounting_date", flat=True)
            .distinct()
        )
        jm_mondays: set[date] = {_get_monday(d) for d in jm_time_dates}

        all_mondays = sorted(set(xero_weeks.keys()) | jm_mondays)

        weeks = [
            _reconcile_week(monday, xero_weeks.get(monday), staff_map) for monday in all_mondays
        ]

        grand_xero = sum(w["totals"]["xero_gross"] for w in weeks)
        grand_jm = sum(w["totals"]["jm_cost"] for w in weeks)
        grand_diff = grand_jm - grand_xero
        grand_pct = (grand_diff / grand_xero * 100) if grand_xero else 0.0

        return PayrollReconciliationData(
            weeks=weeks,
            staff_summaries=_build_staff_summaries(weeks),
            heatmap=_build_heatmap(weeks),
            grand_totals=PayrollGrandTotals(
                xero_gross=round(grand_xero, 2),
                jm_cost=round(grand_jm, 2),
                diff=round(grand_diff, 2),
                diff_pct=round(grand_pct, 1),
            ),
        )
    except Exception as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "operation": "payroll_reconciliation",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                }
            ),
        )
        raise


def get_aligned_date_range(start_date: date, end_date: date) -> AlignedDateRange:
    """Snap arbitrary dates to pay-period-aligned week boundaries.

    Returns the Monday on or before ``start_date`` (after flooring the start to
    ``CompanyDefaults.xero_payroll_start_date``) and the Sunday on or after
    ``end_date``. The end is deliberately never floored: an all-before-payroll
    range comes back empty rather than silently rewritten.
    """
    payroll_start = CompanyDefaults.get_solo().xero_payroll_start_date
    if payroll_start is not None:
        start_date = max(start_date, payroll_start)
    return AlignedDateRange(
        aligned_start=_get_monday(start_date),
        aligned_end=_get_monday(end_date) + timedelta(days=6),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


class _XeroStaffWeek(TypedDict):
    """One staff member's Xero side of a week, summed across pay runs."""

    hours: float
    timesheet_hours: float
    leave_hours: float
    gross: float


class _JMStaffWeek(TypedDict):
    """One staff member's JM side of a week."""

    hours: float
    cost: float


def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _build_staff_xero_map() -> dict[str, Staff]:
    """Map xero_user_id (str) -> Staff object."""
    return {
        staff.xero_user_id: staff
        for staff in Staff.objects.exclude(xero_user_id__isnull=True)
        if staff.xero_user_id is not None  # narrows the exclude() for the type checker
    }


def _slip_display_name(slip: _PaySlipRow, staff_map: dict[str, Staff]) -> str:
    """Resolve the display name a slip's hours are booked under.

    Matched staff use their JM display name so the two sides key together; an
    unmatched slip falls back to Xero's denormalised name. Both missing is a
    sync defect the report cannot reconcile around, so it fails loudly
    (ADR 0015) instead of emitting a null-named row v1 would have 500'd on
    at the serializer.
    """
    staff = staff_map.get(str(slip.xero_employee_id))
    if staff is not None:
        return staff.get_display_name()
    if slip.employee_name is None:
        raise ValueError(
            f"Xero pay slip {slip.xero_id} (employee {slip.xero_employee_id}) has "
            "no employee_name and no Staff with a matching xero_user_id"
        )
    return slip.employee_name


def _get_xero_week_data(
    pay_runs: list[_PayRunRow], staff_map: dict[str, Staff]
) -> dict[str, _XeroStaffWeek]:
    """Xero payslip data summed across all pay runs for one week."""
    result: dict[str, _XeroStaffWeek] = {}
    for pay_run in pay_runs:
        for slip in pay_run.pay_slips.all():
            name = _slip_display_name(slip, staff_map)
            entry = result.get(name)
            if entry is None:
                entry = _XeroStaffWeek(hours=0.0, timesheet_hours=0.0, leave_hours=0.0, gross=0.0)
                result[name] = entry
            entry["hours"] += float(slip.timesheet_hours + slip.leave_hours)
            entry["timesheet_hours"] += float(slip.timesheet_hours)
            entry["leave_hours"] += float(slip.leave_hours)
            entry["gross"] += float(slip.gross_earnings)
    return result


def _get_jm_week_data(week_start: date, week_end: date) -> dict[str, _JMStaffWeek]:
    """JM CostLine time data for one week, keyed by staff display name."""
    lines = CostLine.objects.filter(
        kind="time",
        cost_set__kind="actual",
        accounting_date__gte=week_start,
        accounting_date__lte=week_end,
    ).select_related("staff")

    hours_by_name: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    cost_by_name: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in lines:
        if line.staff is None:
            # Staff-less time lines from restored pre-FK data are
            # invisible to the reconciliation rather than a crash.
            continue
        name = line.staff.get_display_name()
        hours_by_name[name] += line.quantity
        cost_by_name[name] += line.total_cost

    return {
        name: _JMStaffWeek(hours=float(hours_by_name[name]), cost=float(cost_by_name[name]))
        for name in hours_by_name
    }


def _reconcile_week(
    monday: date,
    xero_pay_runs: list[_PayRunRow] | None,
    staff_map: dict[str, Staff],
) -> PayrollWeek:
    """Reconcile one week. Xero pay runs may be None for JM-only weeks."""
    jm_week_start = monday
    jm_week_end = monday + timedelta(days=6)

    xero_data: dict[str, _XeroStaffWeek] = {}
    xero_period_start: str | None = None
    xero_period_end: str | None = None
    payment_date: str | None = None

    if xero_pay_runs:
        xero_data = _get_xero_week_data(xero_pay_runs, staff_map)
        # Use the earliest period start / latest period end across pay runs
        xero_period_start = min(pr.period_start_date for pr in xero_pay_runs).isoformat()
        xero_period_end = max(pr.period_end_date for pr in xero_pay_runs).isoformat()
        payment_date = max(pr.payment_date for pr in xero_pay_runs).isoformat()

    jm_data = _get_jm_week_data(jm_week_start, jm_week_end)

    all_names = sorted(set(xero_data.keys()) | set(jm_data.keys()))

    staff_rows: list[PayrollStaffWeekRow] = []
    total_xero_gross = 0.0
    total_jm_cost = 0.0
    total_xero_hours = 0.0
    total_jm_hours = 0.0
    mismatch_count = 0

    for name in all_names:
        xero = xero_data.get(name)
        jm = jm_data.get(name)

        xero_gross = xero["gross"] if xero is not None else 0.0
        jm_cost = jm["cost"] if jm is not None else 0.0
        xero_hrs = xero["hours"] if xero is not None else 0.0
        jm_hrs = jm["hours"] if jm is not None else 0.0
        cost_diff = jm_cost - xero_gross
        hrs_diff = jm_hrs - xero_hrs

        xero_rate = xero_gross / xero_hrs if xero_hrs else 0.0
        jm_rate = jm_cost / jm_hrs if jm_hrs else 0.0
        hours_cost_impact = hrs_diff * xero_rate
        rate_cost_impact = cost_diff - hours_cost_impact

        total_xero_gross += xero_gross
        total_jm_cost += jm_cost
        total_xero_hours += xero_hrs
        total_jm_hours += jm_hrs

        if xero is None:
            row_status = "jm_only"
        elif jm is None:
            row_status = "xero_only"
        elif abs(cost_diff) > float(THRESHOLD):
            row_status = "mismatch"
        else:
            row_status = "ok"

        if row_status != "ok":
            mismatch_count += 1

        staff_rows.append(
            PayrollStaffWeekRow(
                name=name,
                xero_hours=xero_hrs,
                xero_timesheet_hours=xero["timesheet_hours"] if xero is not None else 0.0,
                xero_leave_hours=xero["leave_hours"] if xero is not None else 0.0,
                xero_gross=xero_gross,
                xero_rate=round(xero_rate, 2),
                jm_hours=jm_hrs,
                jm_cost=jm_cost,
                jm_rate=round(jm_rate, 2),
                hours_diff=hrs_diff,
                cost_diff=cost_diff,
                hours_cost_impact=round(hours_cost_impact, 2),
                rate_cost_impact=round(rate_cost_impact, 2),
                status=row_status,
            )
        )

    return PayrollWeek(
        week_start=jm_week_start.isoformat(),
        xero_period_start=xero_period_start,
        xero_period_end=xero_period_end,
        payment_date=payment_date,
        totals=PayrollWeekTotals(
            xero_gross=total_xero_gross,
            jm_cost=total_jm_cost,
            diff=total_jm_cost - total_xero_gross,
            xero_hours=total_xero_hours,
            jm_hours=total_jm_hours,
        ),
        mismatch_count=mismatch_count,
        staff=staff_rows,
    )


class _StaffAccum(TypedDict):
    """Running per-staff totals while folding weeks into summaries."""

    xero_hours: float
    xero_gross: float
    jm_hours: float
    jm_cost: float
    hours_cost_impact: float
    rate_cost_impact: float
    weeks_with_mismatch: int
    weeks_present: int


def _build_staff_summaries(weeks: list[PayrollWeek]) -> list[PayrollStaffSummary]:
    """Aggregate per-staff totals across all weeks."""
    by_name: defaultdict[str, _StaffAccum] = defaultdict(
        lambda: _StaffAccum(
            xero_hours=0.0,
            xero_gross=0.0,
            jm_hours=0.0,
            jm_cost=0.0,
            hours_cost_impact=0.0,
            rate_cost_impact=0.0,
            weeks_with_mismatch=0,
            weeks_present=0,
        )
    )

    for week in weeks:
        for row in week["staff"]:
            acc = by_name[row["name"]]
            acc["xero_hours"] += row["xero_hours"]
            acc["xero_gross"] += row["xero_gross"]
            acc["jm_hours"] += row["jm_hours"]
            acc["jm_cost"] += row["jm_cost"]
            acc["hours_cost_impact"] += row["hours_cost_impact"]
            acc["rate_cost_impact"] += row["rate_cost_impact"]
            acc["weeks_present"] += 1
            if row["status"] != "ok":
                acc["weeks_with_mismatch"] += 1

    result: list[PayrollStaffSummary] = []
    for name in sorted(by_name):
        acc = by_name[name]
        result.append(
            PayrollStaffSummary(
                name=name,
                xero_hours=round(acc["xero_hours"], 2),
                xero_gross=round(acc["xero_gross"], 2),
                jm_hours=round(acc["jm_hours"], 2),
                jm_cost=round(acc["jm_cost"], 2),
                hours_diff=round(acc["jm_hours"] - acc["xero_hours"], 2),
                cost_diff=round(acc["jm_cost"] - acc["xero_gross"], 2),
                hours_cost_impact=round(acc["hours_cost_impact"], 2),
                rate_cost_impact=round(acc["rate_cost_impact"], 2),
                weeks_present=acc["weeks_present"],
                weeks_with_mismatch=acc["weeks_with_mismatch"],
            )
        )

    return result


def _build_heatmap(weeks: list[PayrollWeek]) -> PayrollHeatmap:
    """Build week x staff grid of cost differences for heatmap display."""
    all_names: set[str] = set()
    for week in weeks:
        for row in week["staff"]:
            all_names.add(row["name"])

    staff_names = sorted(all_names)
    rows: list[PayrollHeatmapRow] = []
    for week in weeks:
        staff_by_name = {row["name"]: row for row in week["staff"]}
        cells: dict[str, float | None] = {}
        for name in staff_names:
            match = staff_by_name.get(name)
            cells[name] = round(match["cost_diff"], 2) if match is not None else None
        rows.append(PayrollHeatmapRow(week_start=week["week_start"], cells=cells))

    return PayrollHeatmap(staff_names=staff_names, rows=rows)
