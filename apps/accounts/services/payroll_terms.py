"""Effective payroll terms used for salary costing and roster comparisons."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.core.models import CompanyDefaults

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
CENT = Decimal("0.01")


def term_on(staff: Staff, target_date: date) -> StaffPayrollTerm | None:
    """Return the latest Xero term effective on a date."""
    return (
        staff.payroll_terms.filter(effective_from__lte=target_date)
        .order_by("-effective_from")
        .first()
    )


def _weeks(term: StaffPayrollTerm) -> list[dict[str, object]]:
    weeks = term.working_weeks
    if not isinstance(weeks, list) or not weeks:
        raise ValidationError(
            f"Xero working pattern is not configured for {term.staff.get_display_full_name()}."
        )
    if not all(isinstance(week, dict) for week in weeks):
        raise ValidationError(f"Xero returned an invalid working pattern for {term.staff_id}.")
    return weeks


def contracted_hours_on(staff: Staff, target_date: date) -> Decimal:
    """Contracted hours for one day, using Xero terms for salaried staff."""
    term = term_on(staff, target_date)
    if term is None or term.pay_basis != "salary":
        return staff.get_scheduled_hours(target_date)
    weeks = _weeks(term)
    week_index = ((target_date - term.effective_from).days // 7) % len(weeks)
    weekday = WEEKDAYS[target_date.weekday()]
    value = weeks[week_index].get(weekday)
    if value is None:
        raise ValidationError(f"Xero working pattern is missing {weekday}.")
    return Decimal(str(value))


def average_weekly_hours(term: StaffPayrollTerm) -> Decimal:
    """Average contracted hours across the repeating Xero pattern."""
    weeks = _weeks(term)
    totals = [
        sum((Decimal(str(week.get(day, 0))) for day in WEEKDAYS), Decimal("0")) for week in weeks
    ]
    average = sum(totals, Decimal("0")) / Decimal(len(totals))
    if average <= 0:
        raise ValidationError(
            "Xero working pattern has no contracted hours for "
            f"{term.staff.get_display_full_name()}."
        )
    return average


def salary_cost_rate(staff: Staff, target_date: date, *, loaded: bool = True) -> Decimal:
    """Derive the standard hourly salary cost for job allocation."""
    term = term_on(staff, target_date)
    if term is None or term.pay_basis != "salary" or not term.annual_salary:
        raise ValidationError(
            f"Salary terms are not synced from Xero for {staff.get_display_full_name()}."
        )
    rate = term.annual_salary / Decimal("52") / average_weekly_hours(term)
    if loaded:
        loading = CompanyDefaults.get_solo().annual_leave_loading
        rate *= Decimal("1") + loading / Decimal("100")
    return rate.quantize(CENT)
