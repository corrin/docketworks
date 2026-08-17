"""The vocabulary the daily and weekly timesheet reads share.

Both screens answer the same three questions about a time line — is it leave,
does it bill the customer, and how did the day go — and before this module they
answered all three differently. Daily called an unrostered worked day "Weekend
Work" while weekly called the same day "Off"; weekly emitted the glyphs "✓" and
"⚠" where daily emitted words; weekly dropped unpaid lines from its billable
figure and daily kept them. One implementation per concept (ADR 0039), so a
weekly cell now means exactly what the daily row for that staff member and day
means.

Two splits are deliberately kept apart rather than merged, because they answer
different questions:

- the **customer** split (billable / non-billable) covers every line — whether
  the customer is charged does not depend on how the staff member is paid;
- the **payroll** split (billed / unbilled / overtime) covers worked time only
  and drops unpaid 0x lines, which belong to no pay bucket.

Merging them would have to pick one rule and silently move hours on one of the
two screens.

``is_billable`` and ``wage_rate_multiplier`` are read straight off ``meta``
rather than defaulted: both are denormalised onto the line at write time, so a
default could only ever mask bad data.
"""
# Opus: docstring rationale unratified (ADR 0051).

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.job.models.costing import CostLine

if TYPE_CHECKING:
    from apps.accounts.models import Staff

OVERTIME_1_5X = Decimal("1.50")
OVERTIME_2X = Decimal("2.00")
UNPAID_MULTIPLIER = Decimal("0")

# Opus: Leave types reported in their own column. Every other leave type lands in
# other_leave so the leave columns still sum to the leave total — v1 reported
# only these three and silently dropped the rest, which counted in the day's
# hours but appeared in no column.
NAMED_LEAVE_COLUMNS = {
    "Sick Leave": "sick_leave",
    "Annual Leave": "annual_leave",
    "Bereavement Leave": "bereavement_leave",
}


@dataclass(frozen=True)
class HourCategories:
    """One set of time lines, split the two ways the timesheet screens report."""

    billable: Decimal
    non_billable: Decimal
    billed: Decimal
    unbilled: Decimal
    overtime_1_5x: Decimal
    overtime_2x: Decimal
    sick_leave: Decimal
    annual_leave: Decimal
    bereavement_leave: Decimal
    other_leave: Decimal

    @property
    def overtime(self) -> Decimal:
        """Overtime at every multiplier."""
        return self.overtime_1_5x + self.overtime_2x

    @property
    def leave(self) -> Decimal:
        """Leave of every type, named column or not."""
        return self.sick_leave + self.annual_leave + self.bereavement_leave + self.other_leave

    # Opus: docstring rationale unratified (ADR 0051).
    @property
    def total(self) -> Decimal:
        """Every hour in the set.

        Summed from the customer split because that split is the exhaustive
        one: ``categorise`` puts every line in ``billable`` or ``non_billable``
        before it asks any other question. The pay split is not exhaustive —
        unpaid time appears in neither ``billed`` nor ``unbilled``.

        Callers used to re-sum ``line.quantity`` themselves, which is how the
        weekly and daily services each grew their own idea of a week's hours.
        """
        return self.billable + self.non_billable

    # Opus: docstring rationale unratified (ADR 0051).
    @property
    def timesheet(self) -> Decimal:
        """The hours that reach Xero through the Timesheets API.

        Leave goes through the Employee Leave API instead — the only surface
        that debits a leave balance (ADR 0007) — so it is the complement of
        ``leave``, not part of this. Reconciling what we recorded against what
        Xero holds has to compare these two sides separately: a timesheet total
        that included leave would report a shortfall on every week containing
        any.
        """
        return self.total - self.leave


# Opus: docstring rationale unratified (ADR 0051).
def is_billable(line: CostLine) -> bool:
    """Whether the line bills the customer.

    Both keys below are denormalised onto the line at write time — the create
    schema supplies them and every one of the actual time lines in the database
    carries them — so the historic ``meta.get(key, default)`` reads were dead
    fallbacks. Reading the key directly means a line that really is missing it
    surfaces as the data bug it is instead of silently counting as billable
    ordinary time (ADR 0015, ADR 0028).
    """
    return bool(_meta_value(line, "is_billable"))


def wage_rate_multiplier(line: CostLine) -> Decimal:
    """Read the line's wage multiplier: 1x ordinary, 1.5x/2x overtime, 0x unpaid."""
    return Decimal(str(_meta_value(line, "wage_rate_multiplier")))


def _meta_value(line: CostLine, key: str) -> object:
    """Read a denormalised meta key, refusing a line that does not carry it."""
    if key not in line.meta:
        raise ValueError(
            f"Time line {line.id} has no meta.{key}, which every timesheet write sets. "
            "Fix the line rather than reading a default in its place."
        )
    return line.meta[key]


# Opus: docstring rationale unratified (ADR 0051).
def leave_type(line: CostLine) -> str | None:
    """Name the leave the line was booked against, or None for worked time.

    The line's own pay item is the only source that can answer this. "Holiday
    Pay" exists in Xero BOTH as an earnings rate and as a leave type, so a name
    match alone is ambiguous; and the job's name or default pay item can
    disagree with what the line actually carries, which is what let v1's three
    separate leave rules drift apart.

    Returning the name rather than the pay item keeps ``apps.xero`` out of this
    module's imports — the layer contract puts it above the domain apps.

    ``CostLine.clean`` requires the pay item on actual time lines, so a missing
    one is bad data and is refused rather than guessed: reading it as worked
    time would drop the hours out of every payroll column while still counting
    them in the day total (ADR 0015).
    """
    pay_item = line.xero_pay_item
    if pay_item is None:
        raise ValueError(
            f"Time line {line.id} has no xero_pay_item, which actual time lines require. "
            "Fix the line rather than reading it as worked time."
        )
    if not pay_item.uses_leave_api:
        return None
    return str(pay_item.name)


def is_leave(line: CostLine) -> bool:
    """Report whether the line is leave rather than worked time."""
    return leave_type(line) is not None


# Opus: docstring rationale unratified (ADR 0051).
def scheduled_hours(staff: "Staff", target_date: date, *, weekend_enabled: bool) -> Decimal:
    """Return what the staff member was rostered for, zero on a 5-day week's weekend.

    Lived only in the daily service, while the weekly one read the roster
    straight off the model. That was harmless while the weekly grid never
    rendered a weekend — the divergent path was unreachable — and became live
    the moment the grid started showing weekend days that carry hours. The same
    booked Saturday could then be "Unscheduled" on one screen and "Partial" on
    the other.
    """
    if not weekend_enabled and target_date.weekday() >= 5:
        return Decimal("0.0")
    return staff.get_scheduled_hours(target_date)


# Opus: docstring rationale unratified (ADR 0051).
def day_status(hours: Decimal, scheduled_hours: Decimal, *, has_leave: bool) -> str:
    """How one staff member's day went, in words both screens use.

    Leave outranks the hour comparison: someone on approved leave has not
    failed to fill in a timesheet.
    """
    if has_leave:
        return "Leave"
    if scheduled_hours == 0:
        return "Unscheduled" if hours > 0 else "Off"
    if hours == 0:
        return "No Entry"
    if hours >= scheduled_hours:
        return "Complete"
    return "Partial"


def categorise(lines: list[CostLine]) -> HourCategories:
    """Split a set of time lines into the reported hour categories."""
    totals = dict.fromkeys(
        (
            "billable",
            "non_billable",
            "billed",
            "unbilled",
            "overtime_1_5x",
            "overtime_2x",
            "sick_leave",
            "annual_leave",
            "bereavement_leave",
            "other_leave",
        ),
        Decimal("0"),
    )

    for line in lines:
        hours = line.quantity
        # Opus: The customer split covers every line, leave included: whether the
        # customer is charged is independent of how the staff member is paid.
        if is_billable(line):
            totals["billable"] += hours
        else:
            totals["non_billable"] += hours

        leave = leave_type(line)
        if leave is not None:
            totals[NAMED_LEAVE_COLUMNS.get(leave, "other_leave")] += hours
            continue

        multiplier = wage_rate_multiplier(line)
        if multiplier == UNPAID_MULTIPLIER:
            continue
        if is_billable(line):
            totals["billed"] += hours
        else:
            totals["unbilled"] += hours
        if multiplier == OVERTIME_1_5X:
            totals["overtime_1_5x"] += hours
        elif multiplier == OVERTIME_2X:
            totals["overtime_2x"] += hours

    return HourCategories(**totals)
