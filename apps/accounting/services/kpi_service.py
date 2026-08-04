"""KPI calendar: daily billable hours, shop hours, and gross profit for a month.

Ported from v1 ``apps/accounting/services/core.py`` (KPIService), split out of
its 400-line ``get_calendar_data`` monolith (sanctioned rewrite; same outputs).

Ported v1 semantics, kept deliberately:

- Weekends are skipped; public holidays are flagged but still count as working
  days (the sales-pipeline report excludes them from ITS working days — a
  cross-report divergence recorded in rewrite-status).
- ``days_green/amber/red`` count every working day including future ones;
  ``labour_*_days`` and ``profit_*_days`` count elapsed days only.
- The profit day-colour ladder is green >= gp_target, amber >= gp_green — the
  ``_amber`` threshold field is unused there (v1 used the ``_green`` field as
  the amber floor; changing it would change the report).
- ``color_shop`` can only be green (shop share <= 20%) or red: v1 passed the
  target as the value and the value as the green threshold, and 20 >= 25 is
  never true so amber is unreachable. Kept bit-for-bit.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

import holidays
from django.utils import timezone

from apps.accounting.services.billable import is_billable_line
from apps.accounts.staff_directory import get_payroll_excluded_staff_ids
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine


class Thresholds(TypedDict):
    """KPI thresholds from CompanyDefaults."""

    kpi_daily_billable_hours_green: float
    kpi_daily_billable_hours_amber: float
    kpi_daily_gp_target: float
    kpi_daily_shop_hours_percentage: float
    kpi_daily_gp_green: float
    kpi_daily_gp_amber: float


class JobBreakdownRow(TypedDict):
    """One job's profit contribution on one day."""

    job_id: str
    job_number: str
    job_name: str
    company_name: str
    billable_hours: float
    revenue: float
    cost: float
    profit: float
    labour_profit: float
    material_profit: float
    adjustment_profit: float


class _TimeAgg(TypedDict):
    """Per-day aggregation of actual time lines."""

    total_hours: Decimal
    billable_hours: Decimal
    shop_hours: Decimal
    time_revenue: Decimal
    staff_cost: Decimal


class _RevCostAgg(TypedDict):
    """Per-day aggregation of material or adjustment lines."""

    revenue: Decimal
    cost: Decimal


@dataclass
class _JobAcc:
    """Accumulator for one job's lines on one day."""

    job_id: str
    job_number: int
    job_name: str
    company_name: str
    labour_revenue: float = 0.0
    labour_cost: float = 0.0
    material_revenue: float = 0.0
    material_cost: float = 0.0
    adjustment_revenue: float = 0.0
    adjustment_cost: float = 0.0
    billable_hours: float = 0.0


def get_company_thresholds() -> Thresholds:
    """KPI thresholds; CompanyDefaults always exists in a configured system."""
    defaults = CompanyDefaults.get_solo()
    return Thresholds(
        kpi_daily_billable_hours_green=float(defaults.kpi_daily_billable_hours_green),
        kpi_daily_billable_hours_amber=float(defaults.kpi_daily_billable_hours_amber),
        kpi_daily_gp_target=float(defaults.kpi_daily_gp_target),
        kpi_daily_shop_hours_percentage=float(defaults.kpi_daily_shop_hours_percentage),
        kpi_daily_gp_green=float(defaults.kpi_daily_gp_green),
        kpi_daily_gp_amber=float(defaults.kpi_daily_gp_amber),
    )


def get_month_days_range(year: int, month: int) -> tuple[date, date, int]:
    """First day, last day, and day count of the month."""
    _, num_days = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, num_days), num_days


def _get_holidays(year: int, month: int | None = None) -> dict[date, str]:
    """NZ public holidays for the year, optionally filtered to one month."""
    nz_holidays = holidays.country_holidays("NZ", years=year)
    if month:
        return {day: name for day, name in nz_holidays.items() if day.month == month}
    return dict(nz_holidays)


def _get_color(value: float | Decimal, green_threshold: float, amber_threshold: float) -> str:
    if value >= green_threshold:
        return "green"
    if value >= amber_threshold:
        return "amber"
    return "red"


def _aggregate_time_by_date(
    start_date: date, end_date: date, shop_company_id: UUID | None
) -> dict[date, _TimeAgg]:
    """Actual time lines grouped by accounting date, payroll-excluded staff removed."""
    excluded_staff_ids = get_payroll_excluded_staff_ids()
    lines = (
        CostLine.objects.filter(
            cost_set__kind="actual",
            kind="time",
            accounting_date__gte=start_date,
            accounting_date__lte=end_date,
        )
        .exclude(staff_id__in=excluded_staff_ids)
        .select_related("cost_set__job")
    )

    by_date: dict[date, _TimeAgg] = {}
    for line in lines:
        agg = by_date.setdefault(line.accounting_date, _empty_time_agg())
        hours = line.quantity
        agg["total_hours"] += hours
        if is_billable_line(line, shop_company_id):
            agg["billable_hours"] += hours
            agg["time_revenue"] += line.total_rev
        if line.cost_set.job.company_id == shop_company_id:
            agg["shop_hours"] += hours
        agg["staff_cost"] += line.total_cost
    return by_date


def _empty_time_agg() -> _TimeAgg:
    return _TimeAgg(
        total_hours=Decimal("0"),
        billable_hours=Decimal("0"),
        shop_hours=Decimal("0"),
        time_revenue=Decimal("0"),
        staff_cost=Decimal("0"),
    )


def _aggregate_rev_cost_by_date(
    kind: str, start_date: date, end_date: date
) -> dict[date, _RevCostAgg]:
    """Material or adjustment lines grouped by accounting date."""
    by_date: dict[date, _RevCostAgg] = {}
    lines = CostLine.objects.filter(
        cost_set__kind="actual",
        kind=kind,
        accounting_date__gte=start_date,
        accounting_date__lte=end_date,
    )
    for line in lines:
        agg = by_date.setdefault(
            line.accounting_date, _RevCostAgg(revenue=Decimal("0"), cost=Decimal("0"))
        )
        agg["revenue"] += line.total_rev
        agg["cost"] += line.total_cost
    return by_date


def get_job_breakdown_for_date(target_date: date) -> list[JobBreakdownRow]:
    """Per-job profit breakdown for one day, most profitable first."""
    shop_company_id = CompanyDefaults.get_solo().shop_company_id

    cost_lines = CostLine.objects.filter(
        cost_set__kind="actual", accounting_date=target_date
    ).select_related("cost_set__job__company")
    excluded_staff_ids = get_payroll_excluded_staff_ids()

    jobs: dict[int, _JobAcc] = {}
    for line in cost_lines:
        # Time entries by payroll-excluded staff are invisible to this report;
        # material and adjustment lines have no staff and always count.
        if line.kind == "time" and line.staff_id in excluded_staff_ids:
            continue

        job = line.cost_set.job
        acc = jobs.setdefault(
            job.job_number,
            _JobAcc(
                job_id=str(job.id),
                job_number=job.job_number,
                job_name=job.job_display_name,
                company_name=job.company.name if job.company else "",
            ),
        )

        if line.kind == "time":
            if is_billable_line(line, shop_company_id):
                acc.labour_revenue += float(line.total_rev)
                acc.billable_hours += float(line.quantity)
            acc.labour_cost += float(line.total_cost)
        elif line.kind == "material":
            acc.material_revenue += float(line.total_rev)
            acc.material_cost += float(line.total_cost)
        elif line.kind == "adjust":
            acc.adjustment_revenue += float(line.total_rev)
            acc.adjustment_cost += float(line.total_cost)

    result: list[JobBreakdownRow] = []
    for acc in jobs.values():
        labour_profit = acc.labour_revenue - acc.labour_cost
        material_profit = acc.material_revenue - acc.material_cost
        adjustment_profit = acc.adjustment_revenue - acc.adjustment_cost
        result.append(
            JobBreakdownRow(
                job_id=acc.job_id,
                job_number=str(acc.job_number),
                job_name=acc.job_name,
                company_name=acc.company_name,
                billable_hours=acc.billable_hours,
                revenue=acc.labour_revenue + acc.material_revenue + acc.adjustment_revenue,
                cost=acc.labour_cost + acc.material_cost + acc.adjustment_cost,
                profit=labour_profit + material_profit + adjustment_profit,
                labour_profit=labour_profit,
                material_profit=material_profit,
                adjustment_profit=adjustment_profit,
            )
        )

    result.sort(key=lambda row: row["profit"], reverse=True)
    return result


@dataclass
class _DayFigures:
    """One working day's three aggregates."""

    time: _TimeAgg
    material: _RevCostAgg
    adjustment: _RevCostAgg

    @property
    def gross_profit(self) -> Decimal:
        revenue = self.time["time_revenue"] + self.material["revenue"] + self.adjustment["revenue"]
        cost = self.time["staff_cost"] + self.material["cost"] + self.adjustment["cost"]
        return revenue - cost


def _tally_day(
    totals: dict[str, float],
    day: _DayFigures,
    thresholds: Thresholds,
    *,
    elapsed: bool,
) -> str:
    """Fold one day into the monthly totals; return the day's colour."""
    billable_hours = day.time["billable_hours"]
    gross_profit = day.gross_profit

    color = _get_color(
        billable_hours,
        thresholds["kpi_daily_billable_hours_green"],
        thresholds["kpi_daily_billable_hours_amber"],
    )
    match color:
        case "green":
            totals["days_green"] += 1
        case "amber":
            totals["days_amber"] += 1
        case _:
            totals["days_red"] += 1

    if elapsed:
        if billable_hours >= thresholds["kpi_daily_billable_hours_green"]:
            totals["labour_green_days"] += 1
        elif billable_hours >= thresholds["kpi_daily_billable_hours_amber"]:
            totals["labour_amber_days"] += 1
        else:
            totals["labour_red_days"] += 1

        # Green >= gp_target, amber >= gp_green (see module docstring).
        if gross_profit >= thresholds["kpi_daily_gp_target"]:
            totals["profit_green_days"] += 1
        elif gross_profit >= thresholds["kpi_daily_gp_green"]:
            totals["profit_amber_days"] += 1
        else:
            totals["profit_red_days"] += 1

        if day.time["total_hours"] > 0:
            totals["active_workdays"] += 1

    totals["billable_hours"] += float(billable_hours)
    totals["total_hours"] += float(day.time["total_hours"])
    totals["shop_hours"] += float(day.time["shop_hours"])
    totals["gross_profit"] += float(gross_profit)
    totals["material_revenue"] += float(day.material["revenue"])
    totals["adjustment_revenue"] += float(day.adjustment["revenue"])
    totals["time_revenue"] += float(day.time["time_revenue"])
    totals["staff_cost"] += float(day.time["staff_cost"])
    totals["material_cost"] += float(day.material["cost"])
    totals["adjustment_cost"] += float(day.adjustment["cost"])
    totals["material_profit"] += float(day.material["revenue"] - day.material["cost"])
    totals["adjustment_profit"] += float(day.adjustment["revenue"] - day.adjustment["cost"])
    return color


def _build_day_entry(
    current: date,
    day: _DayFigures,
    color: str,
    holiday_dates: dict[date, str],
    thresholds: Thresholds,
) -> dict[str, object]:
    """Build one calendar-day response entry."""
    total_hours = day.time["total_hours"]
    shop_percentage = (
        Decimal(day.time["shop_hours"]) / Decimal(total_hours) * 100
        if total_hours > 0
        else Decimal("0")
    )
    gross_profit = day.gross_profit
    total_revenue = day.time["time_revenue"] + day.material["revenue"] + day.adjustment["revenue"]
    total_cost = day.time["staff_cost"] + day.material["cost"] + day.adjustment["cost"]

    entry: dict[str, object] = {
        "date": current.isoformat(),
        "day": current.day,
        "holiday": current in holiday_dates,
    }
    if current in holiday_dates:
        entry["holiday_name"] = holiday_dates[current]
    entry.update(
        {
            "billable_hours": float(day.time["billable_hours"]),
            "total_hours": float(total_hours),
            "shop_hours": float(day.time["shop_hours"]),
            "shop_percentage": float(shop_percentage),
            "gross_profit": float(gross_profit),
            "color": color,
            "gp_target_achievement": float(
                Decimal(gross_profit) / Decimal(thresholds["kpi_daily_gp_target"]) * 100
            )
            if thresholds["kpi_daily_gp_target"] > 0
            else 0.0,
            "details": {
                "time_revenue": float(day.time["time_revenue"]),
                "material_revenue": float(day.material["revenue"]),
                "adjustment_revenue": float(day.adjustment["revenue"]),
                "total_revenue": float(total_revenue),
                "staff_cost": float(day.time["staff_cost"]),
                "material_cost": float(day.material["cost"]),
                "adjustment_cost": float(day.adjustment["cost"]),
                "total_cost": float(total_cost),
                "profit_breakdown": {
                    "labor_profit": float(day.time["time_revenue"] - day.time["staff_cost"]),
                    "material_profit": float(day.material["revenue"] - day.material["cost"]),
                    "adjustment_profit": float(day.adjustment["revenue"] - day.adjustment["cost"]),
                },
                "job_breakdown": get_job_breakdown_for_date(current),
            },
        }
    )
    return entry


def get_calendar_data(year: int, month: int) -> dict[str, object]:
    """All KPI data for the month: per-day entries, monthly totals, thresholds."""
    defaults = CompanyDefaults.get_solo()
    shop_company_id = defaults.shop_company_id
    thresholds = get_company_thresholds()
    start_date, end_date, _ = get_month_days_range(year, month)

    time_by_date = _aggregate_time_by_date(start_date, end_date, shop_company_id)
    material_by_date = _aggregate_rev_cost_by_date("material", start_date, end_date)
    adjustment_by_date = _aggregate_rev_cost_by_date("adjust", start_date, end_date)
    holiday_dates = _get_holidays(year, month)

    calendar_data: dict[str, dict[str, object]] = {}
    totals = _empty_monthly_totals()
    today = timezone.localdate()

    current = start_date
    while current <= end_date:
        if current.weekday() >= 5:  # Saturday/Sunday
            current += timedelta(days=1)
            continue

        # All weekdays count as working days, holidays included (see module
        # docstring); holidays can still carry financial activity.
        totals["working_days"] += 1
        if current <= today:
            totals["elapsed_workdays"] += 1

        day = _DayFigures(
            time=time_by_date.get(current, _empty_time_agg()),
            material=material_by_date.get(
                current, _RevCostAgg(revenue=Decimal("0"), cost=Decimal("0"))
            ),
            adjustment=adjustment_by_date.get(
                current, _RevCostAgg(revenue=Decimal("0"), cost=Decimal("0"))
            ),
        )
        color = _tally_day(totals, day, thresholds, elapsed=current <= today)
        calendar_data[current.isoformat()] = _build_day_entry(
            current, day, color, holiday_dates, thresholds
        )
        current += timedelta(days=1)

    return {
        "calendar_data": calendar_data,
        "monthly_totals": _finalise_monthly_totals(totals, thresholds),
        "thresholds": thresholds,
        "year": year,
        "month": month,
    }


def _empty_monthly_totals() -> dict[str, float]:
    counters = [
        "billable_hours",
        "total_hours",
        "shop_hours",
        "gross_profit",
        "days_green",
        "days_amber",
        "days_red",
        "labour_green_days",
        "labour_amber_days",
        "labour_red_days",
        "profit_green_days",
        "profit_amber_days",
        "profit_red_days",
        "working_days",
        "elapsed_workdays",
        "active_workdays",
        "remaining_workdays",
        "time_revenue",
        "material_revenue",
        "adjustment_revenue",
        "staff_cost",
        "material_cost",
        "adjustment_cost",
        "material_profit",
        "adjustment_profit",
    ]
    return dict.fromkeys(counters, 0)


def _finalise_monthly_totals(totals: dict[str, float], thresholds: Thresholds) -> dict[str, object]:
    """Return the response totals: accumulators plus derived values and colours."""
    final: dict[str, object] = dict(totals)
    final["remaining_workdays"] = totals["working_days"] - totals["elapsed_workdays"]
    final["total_revenue"] = (
        totals["time_revenue"] + totals["material_revenue"] + totals["adjustment_revenue"]
    )
    final["total_cost"] = totals["staff_cost"] + totals["material_cost"] + totals["adjustment_cost"]

    # Net profit approximates operating expenses as the daily GP target over
    # the elapsed working days.
    elapsed_target = thresholds["kpi_daily_gp_target"] * totals["elapsed_workdays"]
    final["elapsed_target"] = elapsed_target
    final["net_profit"] = totals["gross_profit"] - elapsed_target

    billable_percentage = 0.0
    shop_percentage = 0.0
    avg_daily_gp = 0.0
    avg_daily_gp_so_far = 0.0
    avg_billable_hours_so_far = 0.0

    if totals["total_hours"] > 0:
        billable_percentage = float(
            round(
                Decimal(totals["billable_hours"]) / Decimal(totals["total_hours"]) * 100,
                1,
            )
        )
        shop_percentage = float(
            round(Decimal(totals["shop_hours"] / totals["total_hours"]) * 100, 1)
        )

    if totals["working_days"] > 0:
        avg_daily_gp = float(round(Decimal(totals["gross_profit"] / totals["working_days"]), 2))

    # Averages divide by days that actually have hours so idle days don't
    # dilute them.
    if totals["active_workdays"] > 0:
        avg_daily_gp_so_far = float(
            round(Decimal(totals["gross_profit"]) / Decimal(totals["active_workdays"]), 2)
        )
        avg_billable_hours_so_far = float(
            round(
                Decimal(totals["billable_hours"]) / Decimal(totals["active_workdays"]),
                1,
            )
        )

    final["billable_percentage"] = billable_percentage
    final["shop_percentage"] = shop_percentage
    final["avg_daily_gp"] = avg_daily_gp
    final["avg_daily_gp_so_far"] = avg_daily_gp_so_far
    final["avg_billable_hours_so_far"] = avg_billable_hours_so_far

    final["color_hours"] = _get_color(
        avg_billable_hours_so_far,
        thresholds["kpi_daily_billable_hours_green"],
        thresholds["kpi_daily_billable_hours_amber"],
    )
    final["color_gp"] = _get_color(
        avg_daily_gp_so_far,
        thresholds["kpi_daily_gp_target"],
        thresholds["kpi_daily_gp_target"] / 2,
    )
    # v1's reversed-argument call, kept bit-for-bit (see module docstring).
    final["color_shop"] = _get_color(20.0, shop_percentage, 25.0)
    return final
