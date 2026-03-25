"""
Weekly Payroll Reconciliation: Xero vs DocketWorks

DRAFT for handover to dev. The functions here approximate what the API service
layer will need. The __main__ block just dumps results for validation.

Goal: Xero is system-of-record for payroll (what people are actually paid).
JM is system-of-record for management decisions. They MUST agree.

Data sources:
  Xero side: XeroPayRun -> XeroPaySlip (already synced to ORM)
  JM side:   CostLine(kind='time', cost_set__kind='actual') grouped by staff

Staff linking: Staff.xero_user_id == str(XeroPaySlip.xero_employee_id)
  All 11 active staff have xero_user_id set and match 1:1 with Xero employees.

Week alignment: Xero periods are Sun-Sat, JM weeks are Mon-Sun.
  No weekend work so the one-day offset doesn't matter in practice.

Prior work:
  - adhoc/xero_jm_reconciliation/payroll_reconciliation.py (calls Xero API live)
  - adhoc/xero_jm_reconciliation/HANDOVER.md (reconciliation strategy)
  - docs/plans/xero_jm_reconciliation.md (planned API endpoints)
  This script replaces the adhoc version by using synced ORM data instead of
  live API calls.

Planned API endpoint (from docs/plans):
  GET /api/reports/reconciliation/wages/?year=2025&month=10&mode=aggregate
  GET /api/reports/reconciliation/wages/?year=2025&month=10&mode=matched

=== FINDINGS FROM PRODUCTION DATA (30 weeks, 2025-08 to 2026-02) ===

OVERALL: JM under-reports vs Xero by $52,617 (-10.1%) over 30 weeks.

DISCREPANCY CATEGORIES (in order of impact):

1. LEAVE HOURS NOT IN JM
   Biggest single driver. When staff take leave, Xero records leave hours
   and pays gross. JM often records fewer hours or none.
   Examples from week of 2026-02-09:
     Cindy: Xero 44.5hrs (35.5 ts + 9 leave) $2,093 / JM 26hrs $1,170 = -$923
     Richard: Xero 40hrs (0 ts + 40 leave) $1,532 / JM 40hrs $1,532 = OK that week
     But week of 2026-02-16: Richard Xero 40hrs leave $1,532 / JM 16hrs $613 = -$919

2. RATE DIFFERENCES (same hours, different cost)
   JM unit_cost = wage_rate × multiplier. Xero gross includes components
   JM doesn't capture.
   Examples from week of 2026-02-09:
     Ryan: 45.5hrs both sides, Xero $1,930 vs JM $1,820 = -$110
     Aklesh: 40hrs both sides, Xero $1,442 vs JM $1,164 = -$278
     Connor: 40.5hrs both sides, Xero $1,426 vs JM $1,418 = -$9

3. DUPLICATE PAY RUNS PER WEEK
   Week of 2025-12-01 has TWO pay runs (scheduled $14,831 + unscheduled $304).
   Script maps both to same JM week, so JM gets compared twice.
   Dev needs to handle: sum both Xero runs for same week, or flag unscheduled.

4. ANOMALOUS WEEKS
   2025-11-03: Xero $43,913 vs JM $17,338 — likely back-pay or bonus run
   2025-09-01: Xero $28,591 vs JM $16,848 — similar spike
   These are legitimate Xero payroll events with no JM equivalent.

5. BEN: consistently $0 gross in Xero and $0 cost in JM despite 40hrs.
   Likely inactive/unpaid. Excluded from mismatch analysis in practice.

STAFF THAT MATCH WELL:
  Josef and Michael frequently match exactly — no leave, standard hours,
  correct rates. This confirms the join logic is sound.
"""

import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django  # noqa: E402

django.setup()

from apps.accounts.models import Staff  # noqa: E402
from apps.job.models import CostLine  # noqa: E402
from apps.workflow.models.xero_payroll import XeroPayRun  # noqa: E402

ZERO = Decimal("0")
THRESHOLD = Decimal("0.50")


def get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def build_staff_xero_map() -> dict[str, "Staff"]:
    """Map xero_employee_id (str) -> Staff object.

    All 11 active staff have xero_user_id set and match 1:1 with Xero employees.
    """
    return {
        s.xero_user_id: s
        for s in Staff.objects.exclude(xero_user_id__isnull=True).exclude(
            xero_user_id=""
        )
    }


def get_xero_week_data(
    pay_run: XeroPayRun, staff_map: dict[str, "Staff"]
) -> dict[str, dict]:
    """Xero payslip data for one pay run, keyed by staff display name."""
    result = {}
    for slip in pay_run.pay_slips.all():
        emp_id = str(slip.xero_employee_id)
        staff = staff_map.get(emp_id)
        name = staff.get_display_name() if staff else slip.employee_name
        result[name] = {
            "xero_name": slip.employee_name,
            "hours": slip.timesheet_hours + slip.leave_hours,
            "timesheet_hours": slip.timesheet_hours,
            "leave_hours": slip.leave_hours,
            "gross": slip.gross_earnings,
        }
    return result


def get_jm_week_data(week_start: date, week_end: date) -> dict[str, dict]:
    """JM CostLine time data for one week, keyed by staff display name."""
    lines = CostLine.objects.filter(
        kind="time",
        cost_set__kind="actual",
        accounting_date__gte=week_start,
        accounting_date__lte=week_end,
    )

    staff_by_id = {str(s.id): s for s in Staff.objects.all()}

    by_name: dict[str, dict] = defaultdict(lambda: {"hours": ZERO, "cost": ZERO})
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

    return dict(by_name)


def reconcile_week(pay_run: XeroPayRun, staff_map: dict[str, "Staff"]) -> dict:
    """Reconcile one week. Returns a dict suitable for API serialization.

    Return shape:
    {
        "week_start": date,         # Monday of the JM week
        "xero_period_start": date,
        "xero_period_end": date,
        "payment_date": date,
        "totals": {
            "xero_gross": Decimal,
            "jm_cost": Decimal,
            "diff": Decimal,
            "xero_hours": Decimal,
            "jm_hours": Decimal,
        },
        "mismatch_count": int,
        "staff": [
            {
                "name": str,
                "xero_hours": Decimal,
                "xero_timesheet_hours": Decimal,
                "xero_leave_hours": Decimal,
                "xero_gross": Decimal,
                "jm_hours": Decimal,
                "jm_cost": Decimal,
                "hours_diff": Decimal,
                "cost_diff": Decimal,
                "status": str,  # "ok", "mismatch", "jm_only", "xero_only"
            },
            ...
        ],
    }
    """
    xero_start = pay_run.period_start_date
    xero_end = pay_run.period_end_date
    jm_week_start = get_monday(xero_start + timedelta(days=1))
    jm_week_end = jm_week_start + timedelta(days=6)

    xero_data = get_xero_week_data(pay_run, staff_map)
    jm_data = get_jm_week_data(jm_week_start, jm_week_end)

    all_names = sorted(set(xero_data.keys()) | set(jm_data.keys()))

    staff_rows = []
    total_xero_gross = ZERO
    total_jm_cost = ZERO
    total_xero_hours = ZERO
    total_jm_hours = ZERO
    mismatch_count = 0

    for name in all_names:
        xero = xero_data.get(name, {})
        jm = jm_data.get(name, {})

        xero_gross = xero.get("gross", ZERO)
        jm_cost = jm.get("cost", ZERO)
        xero_hrs = xero.get("hours", ZERO)
        jm_hrs = jm.get("hours", ZERO)
        cost_diff = jm_cost - xero_gross
        hrs_diff = jm_hrs - xero_hrs

        total_xero_gross += xero_gross
        total_jm_cost += jm_cost
        total_xero_hours += xero_hrs
        total_jm_hours += jm_hrs

        if name not in xero_data:
            status = "jm_only"
        elif name not in jm_data:
            status = "xero_only"
        elif abs(cost_diff) > THRESHOLD:
            status = "mismatch"
        else:
            status = "ok"

        if status != "ok":
            mismatch_count += 1

        staff_rows.append(
            {
                "name": name,
                "xero_hours": xero_hrs,
                "xero_timesheet_hours": xero.get("timesheet_hours", ZERO),
                "xero_leave_hours": xero.get("leave_hours", ZERO),
                "xero_gross": xero_gross,
                "jm_hours": jm_hrs,
                "jm_cost": jm_cost,
                "hours_diff": hrs_diff,
                "cost_diff": cost_diff,
                "status": status,
            }
        )

    return {
        "week_start": jm_week_start,
        "xero_period_start": xero_start,
        "xero_period_end": xero_end,
        "payment_date": pay_run.payment_date,
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


def get_all_weeks(num_weeks: int = 30) -> list[dict]:
    """Reconcile all available posted pay runs. Returns list of week dicts."""
    staff_map = build_staff_xero_map()
    pay_runs = XeroPayRun.objects.filter(pay_run_status="Posted").order_by(
        "period_start_date"
    )[:num_weeks]
    return [reconcile_week(pr, staff_map) for pr in pay_runs]


# --- Validation output below - not part of the handover API ---

if __name__ == "__main__":
    import json

    weeks = get_all_weeks()

    print(
        f"\n{'Week':<14} {'Xero gross':>11} {'JM cost':>11} {'Diff':>10} {'Diff%':>7} {'Issues':>6}"
    )
    print("-" * 65)

    grand_xero = ZERO
    grand_jm = ZERO
    for w in weeks:
        t = w["totals"]
        grand_xero += t["xero_gross"]
        grand_jm += t["jm_cost"]
        pct = (t["diff"] / t["xero_gross"] * 100) if t["xero_gross"] else ZERO
        flag = "*" if w["mismatch_count"] > 0 else " "
        print(
            f"{flag}{w['week_start']}  "
            f"${t['xero_gross']:>10,.2f} ${t['jm_cost']:>10,.2f} "
            f"${t['diff']:>+9,.2f} {pct:>+6.1f}% {w['mismatch_count']:>4}"
        )

    print("-" * 65)
    grand_diff = grand_jm - grand_xero
    grand_pct = (grand_diff / grand_xero * 100) if grand_xero else ZERO
    print(
        f" {'TOTAL':<13} "
        f"${grand_xero:>10,.2f} ${grand_jm:>10,.2f} "
        f"${grand_diff:>+9,.2f} {grand_pct:>+6.1f}%"
    )

    # Dump one week as sample JSON for frontend dev
    if weeks:
        sample = weeks[-1]
        print(f"\n--- Sample API response for week of {sample['week_start']} ---")

        # Convert Decimals/dates to strings for JSON
        def to_json(obj):
            if isinstance(obj, (Decimal,)):
                return str(obj)
            if isinstance(obj, date):
                return obj.isoformat()
            raise TypeError(f"Not serializable: {type(obj)}")

        print(json.dumps(sample, indent=2, default=to_json))
