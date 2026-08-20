"""Effective payroll terms used for salary costing and roster comparisons.

Opus: Two questions, one query each, and both refuse rather than guess.

``salary_term_on`` answers "what is this person paid under on this date" and is
the only way to reach a ``StaffPayrollTerm``. It raises when a salaried staff
member has none, because the alternative — reading the manual
``hours_mon..hours_sun`` roster instead — produced a plausible figure on the
timesheet screens for someone the costing pipeline would refuse outright, so
the same person was simultaneously schedulable and unbookable (ADR 0015).

``contracted_hours_on`` answers "what were they contracted for that day". It
reads the term effective ON that date rather than ``Staff.pay_basis``, because
the current basis is not what they were paid under last year — and falls back
to the roster only where the term itself says hourly, never where it is absent.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.core.models import CompanyDefaults

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
CENT = Decimal("0.01")


def _term_on(staff: Staff, target_date: date) -> StaffPayrollTerm | None:
    """Return the latest Xero term effective on a date, or None where none is recorded.

    Opus: Private: absence means two different things to the two public questions
    below, and neither wants a caller deciding which.
    """
    return (
        staff.payroll_terms.filter(effective_from__lte=target_date)
        .order_by("-effective_from")
        .first()
    )


def salary_term_on(staff: Staff, target_date: date) -> StaffPayrollTerm:
    """Return the salaried terms in force on a date, refusing when they are not synced.

    Opus: Raises rather than returning ``StaffPayrollTerm | None`` (ADR 0045): every
    caller wanted the same thing from ``None`` — stop — and each was writing its
    own version of that, so ``price_time_entry`` ran this query twice and
    produced two different messages for one condition.
    """
    term = _term_on(staff, target_date)
    if term is None:
        raise ValidationError(
            f"Payroll terms are not synced from Xero for "
            f"{staff.get_display_full_name()} on {target_date.isoformat()}. "
            "Sync the employee from Xero before costing their time."
        )
    if term.pay_basis != "salary":
        raise ValidationError(
            f"{staff.get_display_full_name()} was not salaried on "
            f"{target_date.isoformat()}; their terms record "
            f"{term.pay_basis or 'no pay basis'}."
        )
    return term


def _working_weeks(term: StaffPayrollTerm) -> list[dict[str, Decimal]]:
    """Return the term's repeating work pattern, validated whole and converted once.

    Opus: Every weekday must be present. The Xero sync writes all seven keys for
    every week, coercing an absent day to zero, so a MISSING key is data that
    did not come through that path — and the two readers used to disagree about
    it: one raised, the other counted it as zero hours, which shrank the
    divisor in ``salary_cost_rate`` and inflated the derived hourly cost a job
    is charged. A present zero is an ordinary non-working day and stays valid.
    """
    weeks = term.working_weeks
    if not isinstance(weeks, list) or not weeks:
        raise ValidationError(
            f"Xero working pattern is not configured for {term.staff.get_display_full_name()}."
        )
    validated: list[dict[str, Decimal]] = []
    for week in weeks:
        if not isinstance(week, dict):
            raise ValidationError(f"Xero returned an invalid working pattern for {term.staff_id}.")
        missing = [day for day in WEEKDAYS if day not in week]
        if missing:
            raise ValidationError(
                f"Xero working pattern for {term.staff.get_display_full_name()} is missing "
                f"{', '.join(missing)}."
            )
        validated.append({day: Decimal(str(week[day])) for day in WEEKDAYS})
    return validated


def contracted_hours_on(staff: Staff, target_date: date) -> Decimal:
    """Contracted hours for one day, from Xero terms where the day was salaried."""
    term = _term_on(staff, target_date)
    if term is None and staff.pay_basis == "salary":
        # Opus: Salaried with nothing synced: the roster is not an answer to this
        # question, it is a different question that happens to return a number.
        raise ValidationError(
            f"Payroll terms are not synced from Xero for "
            f"{staff.get_display_full_name()}, so their contracted hours on "
            f"{target_date.isoformat()} are unknown. Sync the employee from Xero."
        )
    if term is None or term.pay_basis != "salary":
        return staff.get_scheduled_hours(target_date)

    weeks = _working_weeks(term)
    week_index = ((target_date - term.effective_from).days // 7) % len(weeks)
    return weeks[week_index][WEEKDAYS[target_date.weekday()]]


def average_weekly_hours(term: StaffPayrollTerm) -> Decimal:
    """Average contracted hours across the repeating Xero pattern."""
    weeks = _working_weeks(term)
    totals = [sum((week[day] for day in WEEKDAYS), Decimal("0")) for week in weeks]
    average = sum(totals, Decimal("0")) / Decimal(len(totals))
    if average <= 0:
        raise ValidationError(
            "Xero working pattern has no contracted hours for "
            f"{term.staff.get_display_full_name()}."
        )
    return average


def salary_cost_rate(term: StaffPayrollTerm, *, loaded: bool = True) -> Decimal:
    """Derive the standard hourly salary cost for job allocation.

    Opus: Takes the term, not the staff member and a date: the caller has already
    resolved it through ``salary_term_on``, and resolving it again here is the
    second query and the second refusal message this module used to carry.
    """
    if not term.annual_salary:
        raise ValidationError(
            f"Xero holds no annual salary for {term.staff.get_display_full_name()} "
            f"from {term.effective_from.isoformat()}."
        )
    rate = term.annual_salary / Decimal("52") / average_weekly_hours(term)
    if loaded:
        loading = CompanyDefaults.get_solo().annual_leave_loading
        rate *= Decimal("1") + loading / Decimal("100")
    return rate.quantize(CENT)
