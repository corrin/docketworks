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

from dataclasses import dataclass
from decimal import Decimal

from apps.job.models.costing import CostLine

OVERTIME_1_5X = Decimal("1.50")
OVERTIME_2X = Decimal("2.00")
UNPAID_MULTIPLIER = Decimal("0")

# Leave types reported in their own column. Every other leave type lands in
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


def day_status(hours: float, scheduled_hours: float, *, has_leave: bool) -> str:
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
        # The customer split covers every line, leave included: whether the
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
