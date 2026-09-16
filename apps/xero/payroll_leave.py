"""Reconciling a staff member's Xero leave for a payroll week.

Opus: Split from ``payroll_push`` because leave is a different Xero surface with
different rules: only the Employee Leave API debits a leave balance, and
unlike timesheets, leave cannot be deleted once the employee sits in a draft
pay run — which is why the posting run reconciles leave BEFORE creating the
pay run (KAN-326).

The reconcile is a three-way match, not a wipe-and-rewrite: leave that already
matches is left alone, stale leave with an overlapping desired request is
UPDATED in place (Xero allows updates while a draft pay run exists, but not
deletions), and only leave with no counterpart is deleted.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from xero_python.payrollnz import EmployeeLeave, LeavePeriod, PayrollNzApi

from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.models.costing import CostLine
from apps.xero import payroll_sdk
from apps.xero.constants import PAYROLL_SLEEP_SECONDS, PAYROLL_UNIT_PRECISION
from apps.xero.helpers import as_date
from apps.xero.models import XeroPayRun

if TYPE_CHECKING:
    from apps.xero.models import XeroPayItem
    from apps.xero.payroll_push import _WeekWindow

logger = logging.getLogger(__name__)


def require_pay_item(line: CostLine) -> "XeroPayItem":
    """Return the line's pay item, refusing a line that has none.

    Fable: The one implementation for both payroll surfaces. This module and
    ``payroll_push`` each carried a private ``_pay_item`` copy — this one typed
    ``-> Any`` — and since push already imports leave, this is the shared home
    that adds no import edge. Not ``hour_categories``: the layer contract bans
    a domain module naming ``XeroPayItem``, even type-only.
    """
    if line.xero_pay_item is None:
        raise ValueError(f"CostLine {line.id} has no xero_pay_item")
    return line.xero_pay_item


class DraftPayRunBlocksLeaveError(ValueError):
    """Xero refused a leave change because the employee sits in a draft pay run.

    Opus: Its own class because the fix is an operator action in the Xero UI, not a
    retry: draft pay runs cannot be deleted through the API.
    """


class SpanningLeaveOverlapError(ValueError):
    """Recorded leave sits under a Xero application that crosses the week boundary.

    Fable: Its own class for the same reason as the draft-pay-run block: the fix is
    an operator action in Xero, not a retry. The post may only write leave inside
    the week it is posting, and a spanning application is not its to edit; writing
    the recorded leave beside it paid the days twice and debited the balance twice
    (KAN-356), so the week refuses instead and names the application to fix.
    """


class LeaveRequestSpec(TypedDict):
    """One leave request Docketworks wants to exist in Xero."""

    leave_type_id: str
    start_date: date
    end_date: date
    total_units: Decimal
    description: str


LeaveKey = tuple[str, date, date, Decimal]


@dataclass(frozen=True)
class _LeaveSession:
    """The Xero call context every leave operation in a reconcile shares.

    Opus: Bundled rather than threaded through each helper: the tenant, the client
    and the employee are fixed for the whole reconcile, and passing them
    individually made the signatures wider than the arguments that actually
    vary.
    """

    api: PayrollNzApi
    tenant_id: str
    employee_id: UUID
    week: "_WeekWindow"


def _units_within_week(leave: EmployeeLeave, week: "_WeekWindow") -> Decimal:
    """Sum the hours a Xero leave record pays inside the payroll week.

    Opus: Xero collapses leave into one period per pay period and keeps only the
    total — per-day breakdowns sent to the API are discarded (KAN-326) — so the
    total is the only unit figure that round-trips, and therefore the only one
    leave can be matched on. ``number_of_units_taken`` is the CONSUMED amount,
    a different quantity, and is never a substitute.

    Fable: Summed over the periods inside the week rather than over all of them.
    For leave contained in the week the two are the same figure; for leave that
    crosses the week boundary Xero holds one period per week it touches, and the
    in-week one is what this week's pay run pays (KAN-356). A spanning record
    with no period in a week it overlaps contradicts that contract, and the
    figure is refused rather than guessed.
    """
    periods = leave.periods or []
    if not periods:
        raise ValueError(f"Xero leave {leave.leave_id} has no periods")
    total = Decimal("0")
    matched = False
    for period in periods:
        period_start = as_date(period.period_start_date)
        period_end = as_date(period.period_end_date)
        if period_start is None or period_end is None:
            raise ValueError(
                f"Xero leave {leave.leave_id} has a period with an unreadable date range: "
                f"{period.period_start_date!r} to {period.period_end_date!r}"
            )
        if not (week.start <= period_start and period_end <= week.end):
            continue
        if period.number_of_units is None:
            raise ValueError(
                f"Xero leave {leave.leave_id} period {period_start} has no number_of_units"
            )
        matched = True
        total += Decimal(str(period.number_of_units))
    if not matched:
        raise ValueError(
            f"Xero leave {leave.leave_id} ({leave.start_date} to {leave.end_date}) overlaps "
            f"the payroll week {week.start}-{week.end} but carries no period inside it"
        )
    return total.quantize(PAYROLL_UNIT_PRECISION)


def _leave_key(leave_type_id: str, start: date, end: date, units: Decimal) -> LeaveKey:
    """Build the identity leave is matched on across a reconcile."""
    return (str(leave_type_id), start, end, Decimal(str(units)).quantize(PAYROLL_UNIT_PRECISION))


def _build_leave_requests(lines: Sequence[CostLine]) -> list[LeaveRequestSpec]:
    """Derive the leave requests the timesheet says should exist.

    Opus: One request per contiguous run of dates per leave type, carrying the run's
    total. Mixed hours across days (8/8/8/4.5) stay ONE request with the total,
    because that is the only representation Xero preserves.
    """
    day_totals: defaultdict[str, defaultdict[date, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )
    names: dict[str, str] = {}
    for line in lines:
        pay_item = require_pay_item(line)
        leave_type_id = str(pay_item.xero_id)
        day_totals[leave_type_id][line.accounting_date] += line.quantity
        names[leave_type_id] = str(pay_item.name)

    specs: list[LeaveRequestSpec] = []
    for leave_type_id, by_date in day_totals.items():
        for start_day, end_day in _contiguous_spans(sorted(by_date)):
            total = sum(
                (units for day, units in by_date.items() if start_day <= day <= end_day),
                Decimal("0"),
            )
            specs.append(
                LeaveRequestSpec(
                    leave_type_id=leave_type_id,
                    start_date=start_day,
                    end_date=end_day,
                    total_units=total.quantize(PAYROLL_UNIT_PRECISION),
                    description=names[leave_type_id],
                )
            )
    return specs


def _contiguous_spans(days: Sequence[date]) -> list[tuple[date, date]]:
    """Collapse sorted dates into (first, last) runs of consecutive days."""
    spans: list[tuple[date, date]] = []
    span_start = span_end = days[0]
    for day in days[1:]:
        if day == span_end + timedelta(days=1):
            span_end = day
        else:
            spans.append((span_start, span_end))
            span_start = span_end = day
    spans.append((span_start, span_end))
    return spans


def _leave_payload(spec: LeaveRequestSpec, week: "_WeekWindow") -> EmployeeLeave:
    """Build the one leave shape the Xero NZ API honours.

    Opus: Verified live (KAN-326): per-day periods are accepted but their units are
    DISCARDED — Xero recomputes them from the employee's working pattern. A
    single period spanning the payroll week with the total units is stored
    exactly as sent, and more than one period per pay period is rejected on
    update ("Multiple PayPeriods are not allowed").
    """
    if spec["end_date"] < spec["start_date"]:
        raise ValueError(f"Leave ends {spec['end_date']} before it starts {spec['start_date']}")
    if not (week.start <= spec["start_date"] and spec["end_date"] <= week.end):
        raise ValueError(
            f"Leave {spec['start_date']}-{spec['end_date']} falls outside the payroll "
            f"week {week.start}-{week.end}"
        )
    if spec["total_units"] <= 0:
        raise ValueError(f"Leave total_units must be positive, got {spec['total_units']}")
    return EmployeeLeave(
        leave_type_id=spec["leave_type_id"],
        description=spec["description"] or f"Leave from {spec['start_date']} to {spec['end_date']}",
        start_date=spec["start_date"],
        end_date=spec["end_date"],
        periods=[
            LeavePeriod(
                period_start_date=week.start,
                period_end_date=week.end,
                number_of_units=float(spec["total_units"]),
                period_status="Approved",
            )
        ],
    )


def _is_draft_pay_run_leave_block(exc: Exception) -> bool:
    """Whether Xero refused a leave change because of a draft pay run.

    Opus: Xero surfaces this only as an error string, with no code. Captured live
    2026-08-02 (KAN-326): "Could not delete the leave request. There is a
    draft pay run for this employee."
    """
    message = str(exc).lower()
    return "leave request" in message and "draft pay run" in message


def _draft_pay_run_summary(tenant_id: str) -> str:
    """Name every draft pay run the operator may need to delete in Xero.

    Opus: Xero blocks leave changes for an employee in ANY draft pay run, not only
    the week being posted, so every mirrored draft is named.
    """
    drafts = list(
        XeroPayRun.objects.filter(xero_tenant_id=tenant_id, pay_run_status="Draft").order_by(
            "period_start_date"
        )
    )
    if not drafts:
        return (
            "the draft pay run (it has not yet synced to Docketworks — "
            "look for it under Payroll then Pay runs)"
        )
    return " and ".join(
        f"the draft pay run for {draft.period_start_date} to {draft.period_end_date}"
        for draft in drafts
    )


def _draft_block_message(action: str, leave_id: str, start: date, end: date, tenant_id: str) -> str:
    """Tell the operator exactly which draft pay run to delete, and where."""
    return (
        f"Xero is blocking a payroll leave change: leave request {leave_id} "
        f"({start} to {end}) needs to be {action} to match the timesheet, but Xero "
        "locks leave while the employee is in a draft pay run, and draft pay runs "
        "cannot be deleted through Xero's API. In Xero go to Payroll then Pay runs, "
        f"delete {_draft_pay_run_summary(tenant_id)}, then post to Xero again."
    )


def _shared_days(start_a: date, end_a: date, start_b: date, end_b: date) -> int:
    """How many calendar days two inclusive date ranges have in common; zero or less is none."""
    return (min(end_a, end_b) - max(start_a, start_b)).days + 1


def _take_overlapping_spec(
    desired: dict[LeaveKey, LeaveRequestSpec], leave_type_id: str, start: date, end: date
) -> LeaveRequestSpec | None:
    """Pop the unmatched request that best overlaps a stale leave record.

    Opus: Same leave type and at least one shared day; largest overlap wins and the
    earliest start breaks ties, so the pairing is deterministic.
    """
    best_key: LeaveKey | None = None
    best_rank: tuple[int, date] | None = None
    for key, spec in desired.items():
        if spec["leave_type_id"] != leave_type_id:
            continue
        overlap = _shared_days(spec["start_date"], spec["end_date"], start, end)
        if overlap <= 0:
            continue
        rank = (-overlap, spec["start_date"])
        if best_rank is None or rank < best_rank:
            best_key, best_rank = key, rank
    return desired.pop(best_key) if best_key is not None else None


@dataclass(frozen=True)
class _DatedLeave:
    """A Xero leave record with its dates read once."""

    leave: EmployeeLeave
    start: date
    end: date


@dataclass(frozen=True)
class _WeekLeave:
    """The employee's Xero leave, sorted by how it sits against the week.

    Fable: ``contained`` is the reconciler's to create, update and delete.
    ``spanning`` overlaps the week but crosses its boundary, so the post may not
    write it, yet Xero pays its in-week period in this week's pay run — it is
    counted, and recorded leave under it is refused (KAN-356). Leave sharing no
    day with the week is neither, and is not carried.
    """

    contained: list[_DatedLeave]
    spanning: list[_DatedLeave]


def _week_leave(employee_id: UUID, week: "_WeekWindow", *, tenant_id: str) -> _WeekLeave:
    """Fetch the employee's leave and sort it against the week."""
    response = payroll_sdk.payroll_api().get_employee_leaves(
        xero_tenant_id=tenant_id, employee_id=str(employee_id)
    )
    contained: list[_DatedLeave] = []
    spanning: list[_DatedLeave] = []
    for leave in response.leave or []:
        leave_start, leave_end = as_date(leave.start_date), as_date(leave.end_date)
        if leave_start is None or leave_end is None:
            raise ValueError(
                f"Xero leave {leave.leave_id} has an unreadable date range: "
                f"{leave.start_date!r} to {leave.end_date!r}"
            )
        if _shared_days(leave_start, leave_end, week.start, week.end) <= 0:
            continue
        dated = _DatedLeave(leave=leave, start=leave_start, end=leave_end)
        if week.start <= leave_start and leave_end <= week.end:
            contained.append(dated)
        else:
            spanning.append(dated)
    return _WeekLeave(contained=contained, spanning=spanning)


def posted_leave_hours(employee_id: UUID, week: "_WeekWindow", *, tenant_id: str) -> Decimal:
    """Total leave hours Xero will pay the employee for the week.

    Opus: The counterpart to ``payroll_push._posted_total``, which sees only the
    Timesheets API. Leave never appears on a timesheet, so without this half a
    recorded-versus-posted comparison reports a shortfall on every week that
    contains any leave at all.

    Fable: Leave crossing the week boundary counts its in-week period. It used to
    count nothing, on the reasoning that it "belongs to neither week" — but Xero
    pays that period in this week's run, so a week doubled by a spanning
    application read back as matching the timesheet (KAN-356).
    """
    held = _week_leave(employee_id, week, tenant_id=tenant_id)
    total = sum(
        (_units_within_week(dated.leave, week) for dated in held.contained + held.spanning),
        Decimal("0"),
    )
    return total.quantize(PAYROLL_UNIT_PRECISION)


def reconcile_leave_for_staff_week(
    employee_id: UUID,
    lines: Sequence[CostLine],
    week: "_WeekWindow",
    *,
    tenant_id: str,
    staff_name: str,
) -> None:
    """Make the employee's Xero leave for the week match the timesheet.

    Opus: Leave that already matches is left untouched. Stale leave with an
    overlapping desired request of the same type is UPDATED in place rather
    than deleted and recreated: Xero permits leave updates while the employee
    is in a draft pay run but refuses deletions (KAN-326), so updating is the
    path that still works late in the week. Only leave with no counterpart is
    deleted, and leave spanning a week boundary is never touched at all.

    Fable: Never touched, and never written over either. Recorded leave sharing a
    day with a spanning application refuses the week before any write, whatever
    the leave type: Xero would pay both applications for those days (KAN-356).
    """
    held = _week_leave(employee_id, week, tenant_id=tenant_id)
    desired: dict[LeaveKey, LeaveRequestSpec] = {
        _leave_key(
            spec["leave_type_id"], spec["start_date"], spec["end_date"], spec["total_units"]
        ): spec
        for spec in _build_leave_requests(lines)
    }
    _refuse_leave_under_spanning_applications(staff_name, held.spanning, desired.values())

    stale: list[_DatedLeave] = []
    for dated in held.contained:
        leave = dated.leave
        if leave.leave_type_id is None:
            raise ValueError(f"Xero leave {leave.leave_id} has no leave_type_id")
        key = _leave_key(
            leave.leave_type_id, dated.start, dated.end, _units_within_week(leave, week)
        )
        if key in desired:
            del desired[key]
        else:
            stale.append(dated)

    session = _LeaveSession(
        api=payroll_sdk.payroll_api(), tenant_id=tenant_id, employee_id=employee_id, week=week
    )
    _resolve_stale_leave(session, stale, desired)
    for spec in desired.values():
        _create_leave(session, spec)


def _refuse_leave_under_spanning_applications(
    staff_name: str, spanning: Sequence[_DatedLeave], desired: Iterable[LeaveRequestSpec]
) -> None:
    """Refuse the week when recorded leave shares a day with a spanning Xero application."""
    for spec in desired:
        for dated in spanning:
            if _shared_days(spec["start_date"], spec["end_date"], dated.start, dated.end) <= 0:
                continue
            raise SpanningLeaveOverlapError(
                f"{staff_name} has {spec['total_units']}h of {spec['description']} recorded for "
                f"{spec['start_date']} to {spec['end_date']}, but Xero already holds leave "
                f"request {dated.leave.leave_id} ({dated.leave.description!r}, {dated.start} to "
                f"{dated.end}) covering those days and reaching outside the payroll week. "
                "Posting would pay both. In Xero, go to Payroll then Leave, and either split "
                "that request at the week boundary and remove this week's part, or delete "
                "it and let the timesheet post it; then post to Xero again. Nothing was "
                "posted for this week."
            )


def _resolve_stale_leave(
    session: _LeaveSession,
    stale: Sequence[_DatedLeave],
    desired: dict[LeaveKey, LeaveRequestSpec],
) -> None:
    """Update stale leave to a desired request where one overlaps, else delete it."""
    for dated in stale:
        replacement = _take_overlapping_spec(
            desired, str(dated.leave.leave_type_id), dated.start, dated.end
        )
        if replacement is not None:
            _update_leave(session, dated.leave, replacement, dated.start, dated.end)
            continue
        _delete_leave(session, dated.leave, dated.start, dated.end)


def _update_leave(
    session: _LeaveSession,
    leave: EmployeeLeave,
    spec: LeaveRequestSpec,
    leave_start: date,
    leave_end: date,
) -> str:
    """Rewrite an existing leave record to the request it should carry."""
    try:
        response = session.api.update_employee_leave(
            xero_tenant_id=session.tenant_id,
            employee_id=str(session.employee_id),
            leave_id=str(leave.leave_id),
            employee_leave=_leave_payload(spec, session.week),
        )
    except Exception as exc:
        if _is_draft_pay_run_leave_block(exc):
            raise DraftPayRunBlocksLeaveError(
                _draft_block_message(
                    "replaced", str(leave.leave_id), leave_start, leave_end, session.tenant_id
                )
            ) from exc
        persist_app_error(
            exc,
            AppErrorContext(
                app="xero",
                function="update_employee_leave",
                additional_context={
                    "employee_id": str(session.employee_id),
                    "leave_id": str(leave.leave_id),
                },
            ),
        )
        raise
    time.sleep(PAYROLL_SLEEP_SECONDS)
    updated = response.leave if response else None
    if updated is None or not updated.leave_id:
        raise ValueError(
            f"Xero returned no leave record after updating {leave.leave_id} "
            f"for employee {session.employee_id}"
        )
    return str(updated.leave_id)


def _delete_leave(
    session: _LeaveSession, leave: EmployeeLeave, leave_start: date, leave_end: date
) -> None:
    """Remove leave the timesheet no longer asks for."""
    try:
        session.api.delete_employee_leave(
            xero_tenant_id=session.tenant_id,
            employee_id=str(session.employee_id),
            leave_id=str(leave.leave_id),
        )
    except Exception as exc:
        if _is_draft_pay_run_leave_block(exc):
            raise DraftPayRunBlocksLeaveError(
                _draft_block_message(
                    "removed", str(leave.leave_id), leave_start, leave_end, session.tenant_id
                )
            ) from exc
        persist_app_error(
            exc,
            AppErrorContext(
                app="xero",
                function="delete_employee_leave",
                additional_context={
                    "employee_id": str(session.employee_id),
                    "leave_id": str(leave.leave_id),
                },
            ),
        )
        raise
    time.sleep(PAYROLL_SLEEP_SECONDS)


def _create_leave(session: _LeaveSession, spec: LeaveRequestSpec) -> str:
    """Create one leave request in Xero and return its id."""
    response = session.api.create_employee_leave(
        xero_tenant_id=session.tenant_id,
        employee_id=str(session.employee_id),
        employee_leave=_leave_payload(spec, session.week),
    )
    time.sleep(PAYROLL_SLEEP_SECONDS)
    if not response or not response.leave:
        raise ValueError(f"Xero returned no leave record for employee {session.employee_id}")
    return str(response.leave.leave_id)
