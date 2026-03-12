import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from apps.accounts.models import Staff
from apps.job.models import CostLine
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models.company_defaults import CompanyDefaults
from apps.workflow.models.xero_payroll import XeroPayRun

from .core import _persist_and_raise

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
THRESHOLD = Decimal("0.50")


class PayrollReconciliationService:
    """Reconciles Xero pay runs against JM CostLine time entries."""

    @staticmethod
    def get_reconciliation_data(start_date: date, end_date: date) -> dict[str, Any]:
        """Build the full payroll reconciliation report.

        Discovers weeks from both Xero pay runs and JM CostLines, then
        cross-compares.  Weeks that exist only on one side are included
        with the missing side showing zeros / null dates.

        Args:
            start_date: Inclusive start of the reporting window.
            end_date: Inclusive end of the reporting window.

        Returns:
            Dict matching PayrollReconciliationResponseSerializer shape.
        """
        payroll_start = CompanyDefaults.get_instance().xero_payroll_start_date
        if payroll_start:
            start_date = max(start_date, payroll_start)

        try:
            staff_map = _build_staff_xero_map()

            # --- Discover Xero weeks ---
            # Filter by overlap: Xero periods start on Sunday while JM
            # weeks are Monday-based, so requiring period_start >= start
            # would miss the first week when the caller passes an aligned
            # Monday.
            pay_runs = (
                XeroPayRun.objects.filter(
                    pay_run_status="Posted",
                    period_end_date__gte=start_date,
                    period_start_date__lte=end_date,
                )
                .prefetch_related("pay_slips")
                .order_by("period_start_date")
            )

            xero_weeks: dict[date, list[XeroPayRun]] = defaultdict(list)
            for pr in pay_runs:
                monday = _get_monday(pr.period_start_date + timedelta(days=1))
                xero_weeks[monday].append(pr)

            # --- Discover JM weeks ---
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

            # --- Union ---
            all_mondays = sorted(set(xero_weeks.keys()) | jm_mondays)

            # --- Reconcile each Monday ---
            weeks = [
                _reconcile_week(
                    monday,
                    xero_weeks.get(monday),
                    staff_map,
                )
                for monday in all_mondays
            ]

            grand_xero = sum(w["totals"]["xero_gross"] for w in weeks)
            grand_jm = sum(w["totals"]["jm_cost"] for w in weeks)
            grand_diff = grand_jm - grand_xero
            grand_pct = (grand_diff / grand_xero * 100) if grand_xero else 0.0

            return {
                "weeks": weeks,
                "staff_summaries": _build_staff_summaries(weeks),
                "heatmap": _build_heatmap(weeks),
                "grand_totals": {
                    "xero_gross": round(grand_xero, 2),
                    "jm_cost": round(grand_jm, 2),
                    "diff": round(grand_diff, 2),
                    "diff_pct": round(grand_pct, 1),
                },
            }
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            _persist_and_raise(
                exc,
                additional_context={"operation": "payroll_reconciliation"},
            )

    @staticmethod
    def get_aligned_date_range(start_date: date, end_date: date) -> dict[str, date]:
        """Snap arbitrary dates to pay-period-aligned week boundaries.

        Returns the Monday on or before ``start_date`` and the Sunday on
        or after ``end_date``.
        """
        payroll_start = CompanyDefaults.get_instance().xero_payroll_start_date
        if payroll_start:
            start_date = max(start_date, payroll_start)
        aligned_start = _get_monday(start_date)
        aligned_end = _get_monday(end_date) + timedelta(days=6)
        return {
            "aligned_start": aligned_start,
            "aligned_end": aligned_end,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _build_staff_xero_map() -> dict[str, Staff]:
    """Map xero_employee_id (str) -> Staff object."""
    return {
        s.xero_user_id: s
        for s in Staff.objects.exclude(xero_user_id__isnull=True).exclude(
            xero_user_id=""
        )
    }


def _get_xero_week_data(
    pay_runs: list[XeroPayRun], staff_map: dict[str, Staff]
) -> dict[str, dict[str, Any]]:
    """Xero payslip data summed across all pay runs for one week."""
    result: dict[str, dict[str, Any]] = {}
    for pay_run in pay_runs:
        for slip in pay_run.pay_slips.all():
            emp_id = str(slip.xero_employee_id)
            staff = staff_map.get(emp_id)
            name = staff.get_display_name() if staff else slip.employee_name
            if name not in result:
                result[name] = {
                    "xero_name": slip.employee_name,
                    "hours": 0.0,
                    "timesheet_hours": 0.0,
                    "leave_hours": 0.0,
                    "gross": 0.0,
                }
            result[name]["hours"] += float(slip.timesheet_hours + slip.leave_hours)
            result[name]["timesheet_hours"] += float(slip.timesheet_hours)
            result[name]["leave_hours"] += float(slip.leave_hours)
            result[name]["gross"] += float(slip.gross_earnings)
    return result


def _get_jm_week_data(week_start: date, week_end: date) -> dict[str, dict[str, float]]:
    """JM CostLine time data for one week, keyed by staff display name."""
    lines = CostLine.objects.filter(
        kind="time",
        cost_set__kind="actual",
        accounting_date__gte=week_start,
        accounting_date__lte=week_end,
    )

    staff_by_id = {str(s.id): s for s in Staff.objects.all()}

    by_name: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"hours": ZERO, "cost": ZERO}
    )
    for line in lines:
        meta = line.meta or {}
        staff_id = meta.get("staff_id")
        if not staff_id:
            continue
        staff = staff_by_id.get(staff_id)
        if not staff:
            continue
        name = staff.get_display_name()
        by_name[name]["hours"] += line.quantity or ZERO
        by_name[name]["cost"] += line.total_cost or ZERO

    return {
        k: {"hours": float(v["hours"]), "cost": float(v["cost"])}
        for k, v in by_name.items()
    }


def _reconcile_week(
    monday: date,
    xero_pay_runs: list[XeroPayRun] | None,
    staff_map: dict[str, Staff],
) -> dict[str, Any]:
    """Reconcile one week.  Xero pay runs may be None for JM-only weeks."""
    jm_week_start = monday
    jm_week_end = monday + timedelta(days=6)

    xero_data: dict[str, dict[str, Any]] = {}
    xero_period_start: str | None = None
    xero_period_end: str | None = None
    payment_date: str | None = None

    if xero_pay_runs:
        xero_data = _get_xero_week_data(xero_pay_runs, staff_map)
        # Use the earliest period start / latest period end across pay runs
        xero_period_start = min(
            pr.period_start_date for pr in xero_pay_runs
        ).isoformat()
        xero_period_end = max(pr.period_end_date for pr in xero_pay_runs).isoformat()
        payment_date = max(pr.payment_date for pr in xero_pay_runs).isoformat()

    jm_data = _get_jm_week_data(jm_week_start, jm_week_end)

    all_names = sorted(set(xero_data.keys()) | set(jm_data.keys()))

    staff_rows: list[dict[str, Any]] = []
    total_xero_gross = 0.0
    total_jm_cost = 0.0
    total_xero_hours = 0.0
    total_jm_hours = 0.0
    mismatch_count = 0

    for name in all_names:
        xero = xero_data.get(name, {})
        jm = jm_data.get(name, {})

        xero_gross = xero.get("gross", 0.0)
        jm_cost = jm.get("cost", 0.0)
        xero_hrs = xero.get("hours", 0.0)
        jm_hrs = jm.get("hours", 0.0)
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

        if name not in xero_data:
            row_status = "jm_only"
        elif name not in jm_data:
            row_status = "xero_only"
        elif abs(cost_diff) > float(THRESHOLD):
            row_status = "mismatch"
        else:
            row_status = "ok"

        if row_status != "ok":
            mismatch_count += 1

        staff_rows.append(
            {
                "name": name,
                "xero_hours": xero_hrs,
                "xero_timesheet_hours": xero.get("timesheet_hours", 0.0),
                "xero_leave_hours": xero.get("leave_hours", 0.0),
                "xero_gross": xero_gross,
                "xero_rate": round(xero_rate, 2),
                "jm_hours": jm_hrs,
                "jm_cost": jm_cost,
                "jm_rate": round(jm_rate, 2),
                "hours_diff": hrs_diff,
                "cost_diff": cost_diff,
                "hours_cost_impact": round(hours_cost_impact, 2),
                "rate_cost_impact": round(rate_cost_impact, 2),
                "status": row_status,
            }
        )

    return {
        "week_start": jm_week_start.isoformat(),
        "xero_period_start": xero_period_start,
        "xero_period_end": xero_period_end,
        "payment_date": payment_date,
        "totals": {
            "xero_gross": total_xero_gross,
            "jm_cost": total_jm_cost,
            "diff": total_jm_cost - total_xero_gross,
            "xero_hours": total_xero_hours,
            "jm_hours": total_jm_hours,
        },
        "mismatch_count": mismatch_count,
        "staff": staff_rows,
    }


def _build_staff_summaries(weeks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate per-staff totals across all weeks."""
    by_name: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "xero_hours": 0.0,
            "xero_gross": 0.0,
            "jm_hours": 0.0,
            "jm_cost": 0.0,
            "hours_cost_impact": 0.0,
            "rate_cost_impact": 0.0,
            "weeks_with_mismatch": 0,
            "weeks_present": 0,
        }
    )

    for week in weeks:
        for row in week["staff"]:
            name = row["name"]
            s = by_name[name]
            s["xero_hours"] += row["xero_hours"]
            s["xero_gross"] += row["xero_gross"]
            s["jm_hours"] += row["jm_hours"]
            s["jm_cost"] += row["jm_cost"]
            s["hours_cost_impact"] += row["hours_cost_impact"]
            s["rate_cost_impact"] += row["rate_cost_impact"]
            s["weeks_present"] += 1
            if row["status"] != "ok":
                s["weeks_with_mismatch"] += 1

    result = []
    for name in sorted(by_name):
        s = by_name[name]
        cost_diff = s["jm_cost"] - s["xero_gross"]
        hours_diff = s["jm_hours"] - s["xero_hours"]
        result.append(
            {
                "name": name,
                "xero_hours": round(s["xero_hours"], 2),
                "xero_gross": round(s["xero_gross"], 2),
                "jm_hours": round(s["jm_hours"], 2),
                "jm_cost": round(s["jm_cost"], 2),
                "hours_diff": round(hours_diff, 2),
                "cost_diff": round(cost_diff, 2),
                "hours_cost_impact": round(s["hours_cost_impact"], 2),
                "rate_cost_impact": round(s["rate_cost_impact"], 2),
                "weeks_present": s["weeks_present"],
                "weeks_with_mismatch": s["weeks_with_mismatch"],
            }
        )

    return result


def _build_heatmap(weeks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build week x staff grid of cost differences for heatmap display."""
    all_names: set[str] = set()
    for week in weeks:
        for row in week["staff"]:
            all_names.add(row["name"])

    staff_names = sorted(all_names)
    rows: list[dict[str, Any]] = []
    for week in weeks:
        cells: dict[str, float | None] = {}
        staff_by_name = {r["name"]: r for r in week["staff"]}
        for name in staff_names:
            row = staff_by_name.get(name)
            cells[name] = round(row["cost_diff"], 2) if row else None
        rows.append({"week_start": week["week_start"], "cells": cells})

    return {"staff_names": staff_names, "rows": rows}
