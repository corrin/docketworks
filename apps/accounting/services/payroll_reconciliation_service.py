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
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol, TypedDict, cast
from uuid import UUID

from apps.accounting.registry import get_provider
from apps.accounting.types import (
    UNPOSTED_STATUSES,
    PayrollRowStatus,
    PayrollXeroSource,
)
from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults
from apps.core.xero_registry import xero_model_manager
from apps.job.models.costing import CostLine
from apps.timesheet.services.xero_hours import build_staff_lookup

ZERO = Decimal("0")
CENT = Decimal("0.01")
TENTH = Decimal("0.1")


def _wire(value: Decimal) -> float:
    """Convert one computed figure to its wire float, quantized to 0.01.

    Fable: The single Decimal-to-float crossing (ADR 0046 sends numbers, the
    Quantity contract in apps/core/schemas.py keeps the arithmetic Decimal).
    Quantized HERE so every published figure is exact at two places — the
    report used to round some columns and ship raw binary artefacts
    (0.30000000000000004) in others.
    """
    return float(value.quantize(CENT))


#: How far ``jm_base_pay`` may sit from Xero's gross before the week is a
#: finding, as a fraction of the gross.
#:
#: Proportional rather than a dollar amount, and deliberately loose: DocketWorks
#: is a management system, accurate enough to decide on — around a percent —
#: while Xero is a payroll system and is exact. Payroll also applies rules
#: DocketWorks does not model at all, so the two agreeing to the cent is not the
#: standard; tracking each other is. A fixed dollar band would be too tight on a
#: full week and too loose on a single hour.
PAY_TOLERANCE_FRACTION = Decimal("0.01")
#: Below this gross, the proportional band is smaller than ordinary rounding,
#: so it is the floor that applies instead.
PAY_TOLERANCE_FLOOR = Decimal("1.00")


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
        """First day of the pay period — a Monday; see ``_payroll_week_of``."""

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

    #: The identity both sides join on (``staff_key``): the Xero employee id,
    #: or a ``staff:`` namespace for staff who cannot appear in a pay run.
    #: Consumers key rows and columns on this, never on ``name`` — two staff
    #: sharing a display name are two people whose money must not merge.
    key: str
    name: str
    xero_hours: float
    xero_timesheet_hours: float
    xero_leave_hours: float
    xero_gross: float
    xero_rate: float
    jm_hours: float
    jm_cost: float
    jm_rate: float
    #: The base-wage figure: ``jm_cost`` with the annual leave loading taken
    #: off. Xero pays the base wage, so this is the side of DocketWorks that
    #: reconciles against a gross; ``jm_cost`` answers the costing question
    #: instead — what this time cost the jobs.
    jm_base_pay: float
    #: ``jm_base_pay - xero_gross``. Small rather than zero: payroll carries
    #: rules we do not model, so the pair is expected to be close, and a large
    #: gap is the finding.
    pay_diff: float
    hours_diff: float
    cost_diff: float
    hours_cost_impact: float
    rate_cost_impact: float
    status: PayrollRowStatus


class PayrollWeekTotals(TypedDict):
    """Aggregate totals for a single reconciliation week."""

    xero_gross: float
    jm_cost: float
    diff: float
    xero_hours: float
    jm_hours: float
    #: Opus: The base-wage total, which is the figure the page judges on — every
    #: row's status compares ``jm_base_pay`` against Xero's gross. Without it the
    #: browser re-summed the column itself, so the page's headline total and the
    #: server's were two computations of one business value (ADR 0020).
    jm_base_pay: float
    #: ``jm_base_pay - xero_gross``: the total of the difference column shown.
    #: ``diff`` above is the LOADED comparison, a different question.
    pay_diff: float


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

    key: str
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


class PayrollHeatmapColumn(TypedDict):
    """One staff column of the heatmap: the join key and the name to show."""

    key: str
    name: str


class PayrollHeatmapRow(TypedDict):
    """Single row in the heatmap grid (one week). Cells are keyed by staff key."""

    week_start: str
    cells: dict[str, float | None]


class PayrollHeatmap(TypedDict):
    """Week x staff cost-difference heatmap.

    Columns carry the staff KEY beside the display name: keyed on names, two
    staff sharing one collapsed into a single column whose cells summed
    whichever of them was the finding.
    """

    columns: list[PayrollHeatmapColumn]
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


class PayrollWeekReconciliation(TypedDict):
    """One week reconciled against the provider, with where the figures came from.

    ``xero_source`` is part of the answer, not metadata: ``live_run`` figures
    are read straight off the week's pay run and can still be settling, while
    ``no_pay_run`` means the provider has computed nothing to compare against
    and a difference would be an artefact of that, not a finding.

    ``unposted_count`` is the page's headline — how many people the provider
    is paying hours we never posted (``UNPOSTED_STATUSES``). Counted here so
    the taxonomy has one owner; the browser re-deriving it from a hand-copied
    status set is how a new status silently vanished from the count.
    """

    week: PayrollWeek
    xero_source: PayrollXeroSource
    unposted_count: int


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
        staff_map = build_staff_lookup()

        # Overlap rather than period_start >= start, so a run straddling the
        # window's first Monday still counts.
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
            monday = _payroll_week_of(pay_run)
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

        # Fable: Summed from the published week totals (re-read as Decimal), not
        # from a parallel unquantized accumulator: a grand total that differs
        # by a cent from the column a reader adds up reads as a defect.
        grand_xero = sum((Decimal(str(w["totals"]["xero_gross"])) for w in weeks), ZERO)
        grand_jm = sum((Decimal(str(w["totals"]["jm_cost"])) for w in weeks), ZERO)
        grand_diff = grand_jm - grand_xero
        grand_pct = (grand_diff / grand_xero * 100) if grand_xero else ZERO

        return PayrollReconciliationData(
            weeks=weeks,
            staff_summaries=_build_staff_summaries(weeks),
            heatmap=_build_heatmap(weeks),
            grand_totals=PayrollGrandTotals(
                xero_gross=_wire(grand_xero),
                jm_cost=_wire(grand_jm),
                diff=_wire(grand_diff),
                diff_pct=float(grand_pct.quantize(TENTH)),
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


def get_week_reconciliation(week_start_date: date) -> PayrollWeekReconciliation:
    """Reconcile one payroll week against what the provider has computed, live.

    The counterpart to ``get_reconciliation_data``, which reads the synced
    ``XeroPaySlip`` mirror and therefore cannot answer until the run is Posted
    and a sync has mirrored it — by which time a mistake has been paid. This
    reads the week's run directly, so it answers straight after posting.

    Driven from the provider's slips rather than our staff list. That is the
    whole point: the costliest error is an employee the provider pays that we
    posted nothing for — they get their pay-template hours, typically a full
    week nobody worked — and iterating our own staff can never surface them.
    """
    provider = get_provider()
    slips = provider.get_pay_slips_for_week(week_start_date)
    staff_map = build_staff_lookup()

    xero_data: dict[str, _XeroStaffWeek] = {}
    for slip in slips:
        _fold_slip(
            xero_data,
            staff_map,
            employee_id=str(slip.employee_external_id),
            employee_name=slip.employee_name,
            slip_ref=f"provider pay slip for employee {slip.employee_external_id}",
            timesheet_hours=slip.timesheet_hours,
            leave_hours=slip.leave_hours,
            gross=slip.gross_earnings,
        )

    week = _reconcile_week_against(week_start_date, xero_data, staff_map, _XeroPeriod())
    return PayrollWeekReconciliation(
        week=week,
        xero_source="live_run" if slips else "no_pay_run",
        unposted_count=sum(1 for row in week["staff"] if row["status"] in UNPOSTED_STATUSES),
    )


def get_aligned_date_range(start_date: date, end_date: date) -> AlignedDateRange:
    """Snap arbitrary dates to pay-period-aligned week boundaries.

    Returns the Monday on or before ``start_date`` (after flooring the start to
    ``CompanyDefaults.xero_payroll_start_date``) and the Sunday ending the week
    on or after
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
    """One staff member's Xero side of a week, summed across pay runs.

    Fable: Decimal throughout, converted to float once at the wire. Money and
    hours accumulated as float is the named defect class in the Quantity
    contract (apps/core/schemas.py): binary rounding error inside what a
    person is paid, and a tolerance comparison that can flip at the boundary.
    """

    name: str
    hours: Decimal
    timesheet_hours: Decimal
    leave_hours: Decimal
    gross: Decimal


class _JMStaffWeek(TypedDict):
    """One staff member's JM side of a week."""

    name: str
    hours: Decimal
    cost: Decimal
    base_pay: Decimal
    #: Carried so the report can say WHY Xero is paying someone we did not
    #: post for: departed is the finding, salaried is expected.
    date_left: date | None
    pay_basis: str | None


def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _payroll_week_of(pay_run: _PayRunRow) -> date:
    """Return the Monday of the week a pay run pays for, refusing a drifted period.

    The period IS the week. `payroll_setup._create_demo_calendar` creates the
    calendar Monday-anchored and fails setup if Xero does not honour it, and
    `accounting.types.require_payroll_week_start` refuses any other start, so a
    period beginning on another weekday means the calendar drifted and every
    figure derived from it is untrustworthy.

    This used to floor `period_start + 1 day` to a Monday, to compensate for a
    belief that Xero periods start on Sunday. They do not — the compensation
    was idempotent under a Monday anchor and so silently harmless, which is
    exactly why it survived.
    """
    if pay_run.period_start_date.weekday() != 0:
        raise ValueError(
            f"Xero pay run period starts on "
            f"{pay_run.period_start_date.strftime('%A %Y-%m-%d')}, not a Monday. "
            "Docketworks requires a Monday-start weekly payroll calendar."
        )
    return pay_run.period_start_date


def _slip_name(
    employee_id: str, employee_name: str | None, staff_map: dict[str, Staff], slip_ref: str
) -> str:
    """Resolve the name a slip's hours are shown under — display only, never the key.

    Matched staff use their full DocketWorks name, so two people sharing a
    first name stay distinguishable; an unmatched slip falls back to the
    provider's denormalised name. Both missing is a sync defect the report
    cannot reconcile around, so it fails loudly (ADR 0015) instead of emitting
    a null-named row v1 would have 500'd on at the serializer.
    """
    staff = staff_map.get(employee_id)
    if staff is not None:
        return staff.get_display_full_name()
    if employee_name is None:
        raise ValueError(
            f"{slip_ref} has no employee_name and no Staff with a matching xero_user_id"
        )
    return employee_name


def _fold_slip(  # noqa: PLR0913 -- One argument per slip fact; both slip shapes flatten here.
    result: dict[str, _XeroStaffWeek],
    staff_map: dict[str, Staff],
    *,
    employee_id: str,
    employee_name: str | None,
    slip_ref: str,
    timesheet_hours: Decimal,
    leave_hours: Decimal,
    gross: Decimal,
) -> None:
    """Fold one slip into the week's Xero side, keyed by employee id.

    Fable: The one fold for both sources of slips — the synced mirror rows and
    the provider's live read. It was written twice over two structurally
    identical shapes, which is the sibling drift ADR 0039 exists to prevent.
    """
    entry = result.get(employee_id)
    if entry is None:
        entry = _XeroStaffWeek(
            name=_slip_name(employee_id, employee_name, staff_map, slip_ref),
            hours=ZERO,
            timesheet_hours=ZERO,
            leave_hours=ZERO,
            gross=ZERO,
        )
        result[employee_id] = entry
    entry["hours"] += timesheet_hours + leave_hours
    entry["timesheet_hours"] += timesheet_hours
    entry["leave_hours"] += leave_hours
    entry["gross"] += gross


def _get_xero_week_data(
    pay_runs: list[_PayRunRow], staff_map: dict[str, Staff]
) -> dict[str, _XeroStaffWeek]:
    """Xero payslip data summed across all pay runs for one week, keyed by employee id."""
    result: dict[str, _XeroStaffWeek] = {}
    for pay_run in pay_runs:
        for slip in pay_run.pay_slips.all():
            _fold_slip(
                result,
                staff_map,
                employee_id=str(slip.xero_employee_id),
                employee_name=slip.employee_name,
                slip_ref=f"Xero pay slip {slip.xero_id} (employee {slip.xero_employee_id})",
                timesheet_hours=slip.timesheet_hours,
                leave_hours=slip.leave_hours,
                gross=slip.gross_earnings,
            )
    return result


def _pay_tolerance(xero_gross: Decimal) -> Decimal:
    """How far base pay may sit from this gross before the row is a finding."""
    return max(abs(xero_gross) * PAY_TOLERANCE_FRACTION, PAY_TOLERANCE_FLOOR)


def staff_key(staff: Staff) -> str:
    """Return the identity both sides of the reconciliation join on.

    The Xero employee id, because that is what a pay slip carries and what
    survives a rename. Display names cannot be the key: ``get_display_name``
    returns the first word only, so two people called Mei-Lin collapse into one
    row while Xero holds a slip for each — merging their money and hiding
    whichever of them is the finding. Xero now owns ``first_name`` and
    ``last_name`` too, so a rename there would silently re-key a name-joined
    row.

    Staff with no Xero link get their own namespace: they cannot appear in a
    pay run, so they can only ever be ``jm_only``.
    """
    return str(staff.xero_user_id) if staff.xero_user_id else f"staff:{staff.id}"


def _line_base_pay(line: CostLine, staff: Staff) -> Decimal:
    """Return what payroll owes for one line, at the rate Xero was given.

    Reconstructed from the same two inputs Xero holds — the employee's base
    wage rate, which ``payroll_employee_sync`` sends as their hourly rate, and
    the line's units and multiplier — rather than by taking the annual leave
    loading back off ``total_cost``.

    Dividing was the earlier approach and it was wrong: ``unit_cost`` is
    denormalised at write time and frozen, while the loading is a setting that
    can change, so every line written under a different loading came out
    skewed. The restored data carries 1.08 while the column reads 20.00, which
    put every reconciled employee about 10% out.
    """
    multiplier = line.meta.get("wage_rate_multiplier")
    if multiplier is None:
        raise ValueError(
            f"CostLine {line.id} has no wage_rate_multiplier; it is denormalised at "
            "write time, so a missing one means the line was not written by the "
            "pricing pipeline."
        )
    return line.quantity * Decimal(str(multiplier)) * staff.base_wage_rate


def _get_jm_week_data(week_start: date, week_end: date) -> dict[str, _JMStaffWeek]:
    """JM CostLine time data for one week, keyed by the Xero employee id."""
    lines = CostLine.objects.filter(
        kind="time",
        cost_set__kind="actual",
        accounting_date__gte=week_start,
        accounting_date__lte=week_end,
    ).select_related("staff")

    hours: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    cost: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    base_pay: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    staff_by_key: dict[str, Staff] = {}
    for line in lines:
        if line.staff is None:
            # Staff-less time lines from restored pre-FK data are
            # invisible to the reconciliation rather than a crash.
            continue
        key = staff_key(line.staff)
        staff_by_key[key] = line.staff
        hours[key] += line.quantity
        cost[key] += line.total_cost
        base_pay[key] += _line_base_pay(line, line.staff)

    return {
        key: _JMStaffWeek(
            name=staff_by_key[key].get_display_full_name(),
            hours=hours[key],
            cost=cost[key],
            base_pay=base_pay[key].quantize(CENT),
            date_left=staff_by_key[key].date_left,
            pay_basis=staff_by_key[key].pay_basis,
        )
        for key in hours
    }


def _reconcile_week(
    monday: date,
    xero_pay_runs: list[_PayRunRow] | None,
    staff_map: dict[str, Staff],
) -> PayrollWeek:
    """Reconcile one week from the synced pay-run mirror."""
    xero_data: dict[str, _XeroStaffWeek] = {}
    period = _XeroPeriod()

    if xero_pay_runs:
        xero_data = _get_xero_week_data(xero_pay_runs, staff_map)
        # Earliest start and latest end across the week's runs.
        period = _XeroPeriod(
            start=min(pr.period_start_date for pr in xero_pay_runs).isoformat(),
            end=max(pr.period_end_date for pr in xero_pay_runs).isoformat(),
            payment_date=max(pr.payment_date for pr in xero_pay_runs).isoformat(),
        )

    return _reconcile_week_against(monday, xero_data, staff_map, period)


@dataclass(frozen=True)
class _XeroPeriod:
    """What the provider stamped on the week's pay runs, or nothing if it holds none.

    One value rather than three parallel arguments: they are only ever set or
    cleared together, and threading them separately was what pushed
    ``_reconcile_week_against`` past the argument limit.
    """

    start: str | None = None
    end: str | None = None
    payment_date: str | None = None


def _row_name(
    key: str,
    xero_data: dict[str, _XeroStaffWeek],
    jm_data: dict[str, _JMStaffWeek],
) -> str:
    """Return the name to show for a row, preferring ours over Xero's denormalised copy."""
    jm = jm_data.get(key)
    if jm is not None:
        return jm["name"]
    return xero_data[key]["name"]


def _unposted_status(key: str, staff_map: dict[str, Staff]) -> PayrollRowStatus:
    """Say WHY Xero is paying someone we posted no hours for.

    One bucket made the report unreadable, because these mean opposite things:

    - **salaried** is expected, not a finding. Their DocketWorks hours allocate
      salary cost to jobs; Xero's regular earnings pay the fixed salary. Those
      two figures answer different questions and must not be compared as wages.
    - **departed** IS the finding: we recorded them as gone and Xero is still
      paying them. The action is specific — run their final pay in Xero and
      terminate them there.
    - **unposted** is someone we hold and believe is current, whose hours never
      reached Xero — either nobody entered them, or the employment dates
      disagree and Xero paid a week we say they were not employed for.
    - **unknown** is a different investigation: nobody in DocketWorks matches
      this employee at all.

    Kept apart because "DocketWorks has no record" is a claim, and making it
    about someone we do hold sends the operator looking for the wrong thing.
    """
    staff = staff_map.get(key)
    if staff is None:
        return "xero_only_unknown"
    if staff.pay_basis == "salary":
        return "xero_only_salaried"
    if staff.date_left is not None:
        return "xero_only_departed"
    return "xero_only_unposted"


def _reconcile_week_against(
    monday: date,
    xero_data: dict[str, _XeroStaffWeek],
    staff_map: dict[str, Staff],
    period: "_XeroPeriod",
) -> PayrollWeek:
    """Reconcile one week against an already-built Xero side.

    Split from ``_reconcile_week`` so the same comparison serves both sources
    of Xero truth: the synced ``XeroPaySlip`` mirror, which only exists once a
    run is Posted, and a live read of the week's run, which answers in the
    minutes after posting when a mistake is still cheap to fix. Only where the
    figures come from differs; how they are compared must not.
    """
    jm_week_start = monday
    jm_week_end = monday + timedelta(days=6)

    jm_data = _get_jm_week_data(jm_week_start, jm_week_end)

    # Keyed by Xero employee id, then sorted by the name each side shows, so
    # two people sharing a first name are two rows that read sensibly.
    all_keys = sorted(
        set(xero_data.keys()) | set(jm_data.keys()),
        key=lambda key: _row_name(key, xero_data, jm_data),
    )

    staff_rows: list[PayrollStaffWeekRow] = []
    total_xero_gross = ZERO
    total_jm_cost = ZERO
    total_jm_base_pay = ZERO
    total_xero_hours = ZERO
    total_jm_hours = ZERO
    mismatch_count = 0

    for key in all_keys:
        xero = xero_data.get(key)
        jm = jm_data.get(key)
        name = _row_name(key, xero_data, jm_data)

        xero_gross = xero["gross"] if xero is not None else ZERO
        jm_cost = jm["cost"] if jm is not None else ZERO
        jm_base_pay = jm["base_pay"] if jm is not None else ZERO
        xero_hrs = xero["hours"] if xero is not None else ZERO
        jm_hrs = jm["hours"] if jm is not None else ZERO
        cost_diff = jm_cost - xero_gross
        pay_diff = jm_base_pay - xero_gross
        hrs_diff = jm_hrs - xero_hrs

        xero_rate = xero_gross / xero_hrs if xero_hrs else ZERO
        jm_rate = jm_cost / jm_hrs if jm_hrs else ZERO
        hours_cost_impact = hrs_diff * xero_rate
        rate_cost_impact = cost_diff - hours_cost_impact

        total_xero_gross += xero_gross
        total_jm_cost += jm_cost
        total_jm_base_pay += jm_base_pay
        total_xero_hours += xero_hrs
        total_jm_hours += jm_hrs

        staff = staff_map.get(key)
        row_status: PayrollRowStatus
        if xero is None:
            row_status = "jm_only"
        elif staff is not None and staff.pay_basis == "salary":
            row_status = "xero_only_salaried"
        elif jm is None or not jm["hours"]:
            row_status = _unposted_status(key, staff_map)
        elif abs(pay_diff) > _pay_tolerance(xero_gross):
            # Judged on base pay against Xero's gross, the two figures that
            # describe the same thing. cost_diff compares the LOADED wage with
            # a gross, which are different questions and never agree.
            row_status = "mismatch"
        else:
            row_status = "ok"

        if row_status not in {"ok", "xero_only_salaried"}:
            mismatch_count += 1

        staff_rows.append(
            PayrollStaffWeekRow(
                key=key,
                name=name,
                xero_hours=_wire(xero_hrs),
                xero_timesheet_hours=_wire(xero["timesheet_hours"] if xero is not None else ZERO),
                xero_leave_hours=_wire(xero["leave_hours"] if xero is not None else ZERO),
                xero_gross=_wire(xero_gross),
                xero_rate=_wire(xero_rate),
                jm_hours=_wire(jm_hrs),
                jm_cost=_wire(jm_cost),
                jm_rate=_wire(jm_rate),
                jm_base_pay=_wire(jm_base_pay),
                pay_diff=_wire(pay_diff),
                hours_diff=_wire(hrs_diff),
                cost_diff=_wire(cost_diff),
                hours_cost_impact=_wire(hours_cost_impact),
                rate_cost_impact=_wire(rate_cost_impact),
                status=row_status,
            )
        )

    return PayrollWeek(
        week_start=jm_week_start.isoformat(),
        xero_period_start=period.start,
        xero_period_end=period.end,
        payment_date=period.payment_date,
        totals=PayrollWeekTotals(
            xero_gross=_wire(total_xero_gross),
            jm_cost=_wire(total_jm_cost),
            diff=_wire(total_jm_cost - total_xero_gross),
            xero_hours=_wire(total_xero_hours),
            jm_hours=_wire(total_jm_hours),
            jm_base_pay=_wire(total_jm_base_pay),
            pay_diff=_wire(total_jm_base_pay - total_xero_gross),
        ),
        mismatch_count=mismatch_count,
        staff=staff_rows,
    )


class _StaffAccum(TypedDict):
    """Running per-staff totals while folding weeks into summaries."""

    name: str
    xero_hours: Decimal
    xero_gross: Decimal
    jm_hours: Decimal
    jm_cost: Decimal
    hours_cost_impact: Decimal
    rate_cost_impact: Decimal
    weeks_with_mismatch: int
    weeks_present: int


def _build_staff_summaries(weeks: list[PayrollWeek]) -> list[PayrollStaffSummary]:
    """Aggregate per-staff totals across all weeks.

    Keyed by the row's ``key``, never its name: ``staff_key``'s own contract —
    two people sharing a display name are two rows whose money must not merge.
    The published week rows carry wire floats, so each figure is re-read as
    Decimal before it is summed.
    """
    by_key: defaultdict[str, _StaffAccum] = defaultdict(
        lambda: _StaffAccum(
            name="",
            xero_hours=ZERO,
            xero_gross=ZERO,
            jm_hours=ZERO,
            jm_cost=ZERO,
            hours_cost_impact=ZERO,
            rate_cost_impact=ZERO,
            weeks_with_mismatch=0,
            weeks_present=0,
        )
    )

    for week in weeks:
        for row in week["staff"]:
            acc = by_key[row["key"]]
            acc["name"] = row["name"]
            acc["xero_hours"] += Decimal(str(row["xero_hours"]))
            acc["xero_gross"] += Decimal(str(row["xero_gross"]))
            acc["jm_hours"] += Decimal(str(row["jm_hours"]))
            acc["jm_cost"] += Decimal(str(row["jm_cost"]))
            acc["hours_cost_impact"] += Decimal(str(row["hours_cost_impact"]))
            acc["rate_cost_impact"] += Decimal(str(row["rate_cost_impact"]))
            acc["weeks_present"] += 1
            if row["status"] not in {"ok", "xero_only_salaried"}:
                acc["weeks_with_mismatch"] += 1

    result: list[PayrollStaffSummary] = []
    for key in sorted(by_key, key=lambda item: by_key[item]["name"]):
        acc = by_key[key]
        result.append(
            PayrollStaffSummary(
                key=key,
                name=acc["name"],
                xero_hours=_wire(acc["xero_hours"]),
                xero_gross=_wire(acc["xero_gross"]),
                jm_hours=_wire(acc["jm_hours"]),
                jm_cost=_wire(acc["jm_cost"]),
                hours_diff=_wire(acc["jm_hours"] - acc["xero_hours"]),
                cost_diff=_wire(acc["jm_cost"] - acc["xero_gross"]),
                hours_cost_impact=_wire(acc["hours_cost_impact"]),
                rate_cost_impact=_wire(acc["rate_cost_impact"]),
                weeks_present=acc["weeks_present"],
                weeks_with_mismatch=acc["weeks_with_mismatch"],
            )
        )

    return result


def _build_heatmap(weeks: list[PayrollWeek]) -> PayrollHeatmap:
    """Build the week x staff grid of cost differences, columns keyed by staff key."""
    names_by_key: dict[str, str] = {}
    for week in weeks:
        for row in week["staff"]:
            names_by_key[row["key"]] = row["name"]

    columns = [
        PayrollHeatmapColumn(key=key, name=names_by_key[key])
        for key in sorted(names_by_key, key=lambda item: names_by_key[item])
    ]
    rows: list[PayrollHeatmapRow] = []
    for week in weeks:
        staff_by_key = {row["key"]: row for row in week["staff"]}
        cells: dict[str, float | None] = {}
        for column in columns:
            match = staff_by_key.get(column["key"])
            cells[column["key"]] = match["cost_diff"] if match is not None else None
        rows.append(PayrollHeatmapRow(week_start=week["week_start"], cells=cells))

    return PayrollHeatmap(columns=columns, rows=rows)
