"""The vocabulary the daily and weekly timesheet reads share.

Opus: Both screens answer the same three questions about a time line — is it leave,
does it bill the customer, and how did the day go — and before this module they
answered all three differently. Daily called an unrostered worked day "Weekend
Work" while weekly called the same day "Off"; weekly emitted the glyphs "✓" and
"⚠" where daily emitted words; weekly dropped unpaid lines from its billable
figure and daily kept them. One implementation per concept (ADR 0039), so a
weekly cell now means exactly what the daily row for that staff member and day
means.

Three splits, not two, and each answers a different question:

- the **customer** split (billable / non-billable) covers every line — whether
  the customer is charged does not depend on how the staff member is paid;
- the **payroll** split (billed / unbilled / overtime) covers worked time only
  and drops unpaid 0x lines, which belong to no pay bucket;
- the **posting** split (timesheet / leave_api / xero_computed) says where each
  hour reaches payroll. It is NOT the same as "is it leave": a public holiday is
  leave the operator sees in a leave column, and Xero computes it from the
  employee's working pattern, so Docketworks posts nothing for it (ADR 0007).
  Anything reconciling against Xero compares ``leave_api``, never ``leave``.

Merging them would have to pick one rule and silently move hours on one of the
two screens.

``is_billable`` and ``wage_rate_multiplier`` are read straight off ``meta``
rather than defaulted: both are denormalised onto the line at write time, so a
default could only ever mask bad data.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from apps.accounts.services.payroll_terms import contracted_hours_on
from apps.job.models.costing import CostLine
from apps.timesheet.models import LeaveType, PostingSurface

if TYPE_CHECKING:
    from apps.accounts.models import Staff

OVERTIME_1_5X = Decimal("1.50")
OVERTIME_2X = Decimal("2.00")
UNPAID_MULTIPLIER = Decimal("0")

# Opus: Which reported column each leave category lands in, keyed by the category
# CODE rather than the Xero pay item's NAME. The name is editable from the
# leave-settings screen, so a rename silently moved hours out of their column
# and into "other" — the reporting-layer form of the rule ADR 0007 lists under
# "Do not". Unpaid and public holiday deliberately SHARE other_leave: the owner
# ruled that a public holiday is leave and must not grow the grid a column, and
# an explicit mapping to a shared column is honest where falling off the end of
# a dict was not.
COLUMN_BY_CODE: Mapping[str, str] = {
    LeaveType.Code.SICK: "sick_leave",
    LeaveType.Code.ANNUAL: "annual_leave",
    LeaveType.Code.BEREAVEMENT: "bereavement_leave",
    LeaveType.Code.UNPAID: "other_leave",
    LeaveType.Code.PUBLIC_HOLIDAY: "other_leave",
}

# Opus: A sixth category must fail here rather than land silently in "other".
if set(COLUMN_BY_CODE) != set(LeaveType.Code.values):
    raise RuntimeError(
        "COLUMN_BY_CODE must name every LeaveType.Code; missing "
        f"{sorted(set(LeaveType.Code.values) - set(COLUMN_BY_CODE))}"
    )


@dataclass(frozen=True, slots=True)
class LeaveCatalogue:
    """The configured leave categories, keyed by what identifies a line as one.

    Opus: Loaded once and passed in, rather than ``LeaveType.for_pay_item`` per
    line: ``categorise`` runs per staff member per day, and a query per line is
    an N+1 over a table with five rows that never change during a request.

    Two keys because two kinds of category identify differently. A category
    Xero posts has a pay item, and the LINE's own pay item is the routing key
    (ADR 0007) — the job's name or default cannot be trusted. A category Xero
    pays itself has no pay item to name, because there is no Xero object for
    it, so its line is identified by the job its category is bound to. That is
    a foreign key, not the job-NAME matching ADR 0007 bans.
    """

    code_by_pay_item: Mapping[UUID, str]
    code_by_job: Mapping[UUID, str]

    @classmethod
    def load(cls) -> "LeaveCatalogue":
        """Read the configured categories once."""
        rows = list(LeaveType.objects.exclude(job=None).select_related("job"))
        return cls(
            # Opus: Leave-API categories ONLY. ``Job.default_xero_pay_item`` is NOT
            # NULL and ``Job.save`` fills it with Ordinary Time, so the
            # public-holiday job carries that rate as a dropdown default it
            # never posts — and indexing it here would classify all 16,731
            # Ordinary Time lines in the database as public holiday.
            code_by_pay_item={
                row.job.default_xero_pay_item_id: row.code
                for row in rows
                if row.job is not None
                and row.job.default_xero_pay_item_id is not None
                and LeaveType.surface_for(row.code) is PostingSurface.LEAVE_API
            },
            # Opus: Only the categories a line cannot name through a pay item,
            # which is the one thing this index is consulted for.
            code_by_job={
                row.job_id: row.code
                for row in rows
                if row.job_id is not None
                and LeaveType.surface_for(row.code) is PostingSurface.XERO_COMPUTED
            },
        )

    def code_for(self, line: CostLine) -> str | None:
        """Name the leave category a line belongs to, or None for worked time."""
        # Opus: The job is asked FIRST, and only for the categories Xero pays
        # itself. Those lines must reach no Xero surface whatever pay item they
        # happen to carry — a restored v1 row, or an explicit pay_item_override
        # on the cost-line API, would otherwise route a public holiday to the
        # Timesheets API and pay the day twice. ADR 0007 makes the line's own
        # pay item the routing key between Xero's two surfaces, which is what
        # the fall-through below does; it cannot answer for hours that reach
        # neither, and a foreign key is not the job-NAME matching it bans.
        computed = self.code_by_job.get(line.cost_set.job_id)
        if computed is not None:
            return computed
        if line.xero_pay_item_id is None:
            raise ValueError(
                f"Time line {line.id} has no xero_pay_item and its job is not a leave "
                "category Xero pays itself. Fix the line rather than reading it as work."
            )
        pay_item = line.xero_pay_item
        if pay_item is None or not pay_item.uses_leave_api:
            return None
        code = self.code_by_pay_item.get(pay_item.id)
        if code is None:
            raise ValueError(
                f"Xero leave type {pay_item.name!r} is not mapped to a Docketworks leave "
                "category, so how it is reported and paid is unknown. Map it under "
                "Timesheets -> Leave settings."
            )
        return code

    def surface_for(self, line: CostLine) -> PostingSurface:
        """Where this line's hours reach payroll."""
        code = self.code_for(line)
        if code is None:
            return PostingSurface.TIMESHEET
        return LeaveType.surface_for(code)


@dataclass(frozen=True)
class HourCategories:
    """One set of time lines, split the three ways the timesheet screens and payroll report."""

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
    #: Hours posted through the Employee Leave API — leave that debits a balance.
    leave_api: Decimal
    #: Hours Xero pays from its own calculation, which Docketworks posts nowhere.
    xero_computed: Decimal

    @property
    def overtime(self) -> Decimal:
        """Overtime at every multiplier."""
        return self.overtime_1_5x + self.overtime_2x

    @property
    def leave(self) -> Decimal:
        """Leave of every type, named column or not.

        Opus: What a person is absent for, which is the reporting question. It is
        NOT the same as what goes to the Leave API — a public holiday is leave
        and is posted nowhere — so anything reconciling against Xero must use
        ``leave_api`` instead.
        """
        return self.sick_leave + self.annual_leave + self.bereavement_leave + self.other_leave

    @property
    def total(self) -> Decimal:
        """Every hour in the set.

        Opus: Summed from the customer split because that split is the exhaustive
        one: ``categorise`` puts every line in ``billable`` or ``non_billable``
        before it asks any other question. The pay split is not exhaustive —
        unpaid time appears in neither ``billed`` nor ``unbilled``.

        Callers used to re-sum ``line.quantity`` themselves, which is how the
        weekly and daily services each grew their own idea of a week's hours.
        """
        return self.billable + self.non_billable

    @property
    def timesheet(self) -> Decimal:
        """The hours that reach Xero through the Timesheets API.

        Opus: Every hour reaches payroll by exactly one of three routes, so this is
        what is left after the two that are not the Timesheets API. It was
        ``total - leave``, which was right only while "is leave" and "goes to
        the Leave API" meant the same thing; a public holiday is leave that
        Xero pays itself, and counting it here would post it a second time.
        """
        return self.total - self.leave_api - self.xero_computed


def is_billable(line: CostLine) -> bool:
    """Whether the line bills the customer.

    Opus: Both keys below are denormalised onto the line at write time — the create
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


def leave_type(line: CostLine, catalogue: LeaveCatalogue) -> str | None:
    """Name the leave category the line was booked against, or None for worked time.

    Opus: Returns the category CODE, not the Xero pay item's name. The name is
    editable from the leave-settings screen, so putting it on the wire made
    every consumer — including the browser — inherit a classification that a
    rename could change (ADR 0007's "Do not", ADR 0028).
    """
    return catalogue.code_for(line)


def is_leave(line: CostLine, catalogue: LeaveCatalogue) -> bool:
    """Report whether the line is leave rather than worked time."""
    return catalogue.code_for(line) is not None


def scheduled_hours(staff: "Staff", target_date: date, *, weekend_enabled: bool) -> Decimal:
    """Return what the staff member was rostered for, zero on a 5-day week's weekend.

    Opus: Lived only in the daily service, while the weekly one read the roster
    straight off the model. That was harmless while the weekly grid never
    rendered a weekend — the divergent path was unreachable — and became live
    the moment the grid started showing weekend days that carry hours. The same
    booked Saturday could then be "Unscheduled" on one screen and "Partial" on
    the other.
    """
    if not weekend_enabled and target_date.weekday() >= 5:
        return Decimal("0.0")
    return contracted_hours_on(staff, target_date)


def day_status(hours: Decimal, scheduled_hours: Decimal, *, has_leave: bool) -> str:
    """How one staff member's day went, in words both screens use.

    Opus: Leave outranks the hour comparison: someone on approved leave has not
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


def categorise(lines: list[CostLine], catalogue: LeaveCatalogue | None = None) -> HourCategories:
    """Split a set of time lines into the reported hour categories.

    Opus: ``catalogue`` is optional only so a caller with one set of lines need not
    build it by hand; passing it is what keeps a per-day loop from reloading
    five rows for every staff member.
    """
    if catalogue is None:
        catalogue = LeaveCatalogue.load()
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
            "leave_api",
            "xero_computed",
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

        leave = catalogue.code_for(line)
        if leave is not None:
            totals[COLUMN_BY_CODE[leave]] += hours
            # Opus: The reported column and the posting surface are different
            # questions: a public holiday reports as leave and posts nowhere.
            if LeaveType.surface_for(leave) is PostingSurface.XERO_COMPUTED:
                totals["xero_computed"] += hours
            else:
                totals["leave_api"] += hours
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
