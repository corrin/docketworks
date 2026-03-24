"""
Shared helpers for extracting Xero and JM hours by staff by week.

Used by management commands (create_overtime_entries, etc.) and scripts.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from apps.accounts.models import Staff
from apps.job.models import CostLine
from apps.workflow.models.xero_payroll import XeroPayRun

# Earliest week to process (pre-Xero payroll data is unreliable)
CUTOFF_DATE = date(2025, 8, 11)


# Mapping from Xero leave display name prefix to JM job name
LEAVE_TYPE_MAP = {
    "Sick Leave": "Sick Leave",
    "Annual Leave": "Annual Leave",
    "Unpaid Leave": "Unpaid Leave",
    "Bereavement Leave": "Bereavement Leave",
    "Stand Down Leave": "Bereavement Leave",  # logged as bereavement in JM
    "Alternative Holidays": "Annual Leave",
    "Holiday Pay": "Annual Leave",
}


def _extract_leave_type(display_name: str) -> str:
    """Extract leave type from Xero display name like 'Sick Leave (22 Sep 2025)'.

    Returns the JM job name for the leave type.
    """
    # Strip date suffix in parentheses
    base = display_name.split("(")[0].strip()
    # Remove " - " suffixes like "Annual Leave - Cash Up"
    # but keep "Stand Down Leave" intact
    for prefix in LEAVE_TYPE_MAP:
        if base.startswith(prefix):
            return LEAVE_TYPE_MAP[prefix]
    return "Sick Leave"  # safe default


def get_xero_hours_by_staff_week() -> list[dict]:
    """Return Xero payroll hours per staff per week from posted pay runs.

    Each dict has:
        week_start (date), xero_employee_id (str), employee_name (str),
        ordinary_hrs (Decimal), ot_hrs (Decimal), leave_hrs (Decimal),
        ordinary_rate (Decimal), ot_rate (Decimal)
    """
    rows = []

    for pr in (
        XeroPayRun.objects.filter(pay_run_status="Posted")
        .prefetch_related("pay_slips")
        .order_by("period_start_date")
    ):
        # Align to Monday (Xero period_start_date is Sunday)
        monday = pr.period_start_date + timedelta(days=1)
        monday = monday - timedelta(days=monday.weekday())

        if monday < CUTOFF_DATE:
            continue

        for slip in pr.pay_slips.all():
            raw = slip.raw_json or {}

            ordinary_hrs = Decimal("0")
            ot_hrs = Decimal("0")
            ordinary_rate = Decimal("0")
            ot_rate = Decimal("0")
            leave_hrs = Decimal("0")

            for line in raw.get("_timesheet_earnings_lines") or []:
                display = line.get("_display_name") or ""
                units = Decimal(str(line.get("_number_of_units") or 0))
                rate = Decimal(str(line.get("_rate_per_unit") or 0))

                if "half" in display.lower():
                    ot_hrs += units
                    ot_rate = rate
                elif "Ordinary" in display:
                    ordinary_hrs += units
                    ordinary_rate = rate

            leave_by_type: dict[str, Decimal] = {}
            for line in raw.get("_leave_earnings_lines") or []:
                units = Decimal(str(line.get("_number_of_units") or 0))
                leave_hrs += units
                display = line.get("_display_name") or ""
                leave_type = _extract_leave_type(display)
                leave_by_type[leave_type] = (
                    leave_by_type.get(leave_type, Decimal("0")) + units
                )

            rows.append(
                {
                    "week_start": monday,
                    "xero_employee_id": str(slip.xero_employee_id),
                    "employee_name": slip.employee_name,
                    "ordinary_hrs": ordinary_hrs,
                    "ot_hrs": ot_hrs,
                    "leave_hrs": leave_hrs,
                    "leave_by_type": leave_by_type,
                    "ordinary_rate": ordinary_rate,
                    "ot_rate": ot_rate,
                }
            )

    return rows


LEAVE_JOB_NAMES = {
    "Annual Leave",
    "Sick Leave",
    "Bereavement Leave",
    "Unpaid Leave",
    "Statutory holiday",
}


def get_jm_hours_for_staff_week(staff_id: str, week_start: date) -> dict:
    """Return JM hours for one staff member for one week.

    Returns dict with:
        jm_total (Decimal) - total hours in JM for the week
        jm_ot (Decimal) - overtime hours (xero_pay_item multiplier > 1)
        jm_leave_by_type (dict[str, Decimal]) - leave hours by job name
    """
    week_end = week_start + timedelta(days=6)

    jm_lines = CostLine.objects.filter(
        kind="time",
        cost_set__kind="actual",
        accounting_date__gte=week_start,
        accounting_date__lte=week_end,
        meta__staff_id=str(staff_id),
    )

    jm_total = jm_lines.aggregate(s=Sum("quantity"))["s"] or Decimal("0")
    jm_ot = jm_lines.filter(
        xero_pay_item__multiplier__gt=Decimal("1"),
    ).aggregate(
        s=Sum("quantity")
    )["s"] or Decimal("0")

    # Leave hours by job name
    jm_leave_by_type: dict[str, Decimal] = {}
    leave_lines = (
        jm_lines.filter(cost_set__job__name__in=LEAVE_JOB_NAMES)
        .values("cost_set__job__name")
        .annotate(total=Sum("quantity"))
    )
    for row in leave_lines:
        jm_leave_by_type[row["cost_set__job__name"]] = row["total"]

    return {
        "jm_total": jm_total,
        "jm_ot": jm_ot,
        "jm_leave_by_type": jm_leave_by_type,
    }


def build_staff_lookup() -> dict[str, Staff]:
    """Build lookup from xero_user_id -> Staff for all staff with Xero IDs."""
    lookup = {}
    for staff in Staff.objects.filter(xero_user_id__isnull=False):
        lookup[staff.xero_user_id] = staff
    return lookup
