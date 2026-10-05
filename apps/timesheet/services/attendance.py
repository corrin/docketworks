"""Clocking in and out: when a person was at work on a day (KAN-376).

It helps the worker and the office see the day, and binds nothing: no pay,
no approval and no entry depends on it. Every function is told the time
(``now``) by its caller, so nothing here reads the clock.

Refusals are raised here, as typed errors a person can read. The table's
constraints state the same facts about a row and are the backstop, never the
message.
"""

from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, NamedTuple, TypedDict
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.errors import AccessDeniedError, ConflictError, InvalidInputError
from apps.core.models import CompanyDefaults
from apps.timesheet.models import AttendanceBreak, AttendanceDay

#: Where a person's day stands, from their attendance row alone.
DayState = Literal["not_clocked_in", "at_work", "clocked_out", "sent"]


class AttendanceData(TypedDict):
    """One person's day as they clocked it, for their own card and the office's row."""

    state: DayState
    clock_in: time | None
    clock_out: time | None
    #: Hours between clock in and clock out; None until both are known. Worked
    #: out here so no screen does the arithmetic.
    here_hours: float | None
    #: The day was sent on a later day than the day it is for.
    sent_late: bool


class ClockingRefusedError(ConflictError):
    """The clock tap does not fit where the day stands."""


def _to_the_minute(moment: datetime) -> time:
    return moment.time().replace(second=0, microsecond=0)


def day_state(row: AttendanceDay | None) -> DayState:
    """Derive the day's state from its row; there is no stored status."""
    if row is None:
        return "not_clocked_in"
    if row.clock_out is None:
        return "at_work"
    if row.submitted_at is None:
        return "clocked_out"
    return "sent"


def _here_hours(row: AttendanceDay) -> float | None:
    if row.clock_out is None:
        return None
    minutes = (row.clock_out.hour * 60 + row.clock_out.minute) - (
        row.clock_in.hour * 60 + row.clock_in.minute
    )
    return round(minutes / 60, 2)


class Window(NamedTuple):
    """A stretch of a day."""

    start: time
    end: time


class BreakData(TypedDict):
    """One break in a person's day, for the calendar and the office's row."""

    id: str
    start: time
    end: time
    paid: bool


def day_breaks(row: AttendanceDay | None) -> list[AttendanceBreak]:
    """Return the day's breaks in the order they happened.

    With ``unpaid_windows`` this is the only reader of the breaks table: the
    day read and the calendar ask here, the arithmetic and the layout ask
    there, and no time, cost or pay figure asks at all.
    """
    if row is None:
        return []
    return list(row.breaks.all())


def unpaid_windows(row: AttendanceDay | None) -> list[Window]:
    """Return the day's unpaid breaks: what comes off the hours to fill.

    A paid break is not here because it changes nothing: that time is paid
    and billed with the job in hand, so entries run through it.
    """
    return [Window(each.start, each.end) for each in day_breaks(row) if not each.paid]


def break_data(each: AttendanceBreak) -> BreakData:
    """Shape one break for the wire."""
    return {"id": str(each.id), "start": each.start, "end": each.end, "paid": each.paid}


def _minutes(moment: time) -> int:
    return moment.hour * 60 + moment.minute


QUARTER_HOUR_MINUTES = 15


class FillData(TypedDict):
    """How much of the day there is to account for, and how far the entries go.

    All three are worked out here so no screen does arithmetic: the worker is
    told "8 hours to fill, 3 entered, 5 to go", never asked to subtract.
    ``to_go_hours`` is negative when more is entered than he was here for;
    that is stated, not refused, because attendance binds nothing.
    """

    to_fill_hours: float
    entered_hours: float
    to_go_hours: float


def paid_span_hours(start: time, finish: time, unpaid: list[Window]) -> Decimal:
    """Hours between two clock times less unpaid breaks, to the nearest quarter hour.

    Only the part of a break inside the clocked span comes off: one he moved
    to before he started or after he finished does not shrink his day.
    Entries are in quarter hours and a real clock is not (06:28 to 15:04), so
    the span is rounded once here and nothing downstream shows "0.1 to go".
    """
    first, last = _minutes(start), _minutes(finish)
    minutes = last - first
    for window in unpaid:
        inside = min(last, _minutes(window.end)) - max(first, _minutes(window.start))
        minutes -= max(inside, 0)
    quarters = (Decimal(minutes) / QUARTER_HOUR_MINUTES).quantize(Decimal("1"), ROUND_HALF_UP)
    return quarters * QUARTER_HOUR_MINUTES / Decimal(60)


def fill_figures(row: AttendanceDay | None, entered: Decimal) -> FillData | None:
    """Return the day's fill figures, or None until both clock times are known."""
    if row is None or row.clock_out is None:
        return None
    to_fill = paid_span_hours(row.clock_in, row.clock_out, unpaid_windows(row))
    return {
        "to_fill_hours": float(to_fill),
        "entered_hours": float(entered),
        "to_go_hours": float(to_fill - entered),
    }


class CalendarBounds(TypedDict):
    """The stretch of the day the worker's calendar opens on."""

    start: time
    end: time


_CALENDAR_MARGIN_MINUTES = 60


def calendar_bounds(
    row: AttendanceDay | None,
    working_day: tuple[time, time],
    entry_times: list[tuple[time, time]],
) -> CalendarBounds:
    """Bound the calendar to the day, with an hour either side.

    The company's working day, stretched to the clocked span when he was
    there outside it, and to any entry outside both. The working day stays in
    view whatever he clocked: a short or odd clocking must not hide the hours
    he would tap to book.
    """
    start, finish = working_day
    if row is not None:
        start = min(start, row.clock_in)
        finish = max(finish, row.clock_in if row.clock_out is None else row.clock_out)
    first = min([_minutes(start), *(_minutes(begin) for begin, _ in entry_times)])
    last = max([_minutes(finish), *(_minutes(end) for _, end in entry_times)])
    first = max(first - _CALENDAR_MARGIN_MINUTES, 0) // 60 * 60
    last = min(last + _CALENDAR_MARGIN_MINUTES, 24 * 60 - 1)
    return {"start": time(first // 60, first % 60), "end": time(last // 60, last % 60)}


def attendance_data(row: AttendanceDay | None) -> AttendanceData:
    """Shape a day's attendance, or its absence, for the wire."""
    if row is None:
        return {
            "state": "not_clocked_in",
            "clock_in": None,
            "clock_out": None,
            "here_hours": None,
            "sent_late": False,
        }
    return {
        "state": day_state(row),
        "clock_in": row.clock_in,
        "clock_out": row.clock_out,
        "here_hours": _here_hours(row),
        "sent_late": row.submitted_at is not None
        and timezone.localdate(row.submitted_at) > row.date,
    }


def day_attendance(staff: Staff, day: date) -> AttendanceData:
    """One person's attendance for one day."""
    return attendance_data(AttendanceDay.objects.filter(staff=staff, date=day).first())


class PendingDay(TypedDict):
    """An earlier day the person has not finished, and how far it got."""

    date: date
    state: DayState


def pending_day(staff: Staff, today: date) -> PendingDay | None:
    """Return the earliest earlier day this person clocked and has not sent, if any.

    A day left clocked in cannot be closed by a tap on a later date: the finish
    time is not known, so it is asked for. A day clocked out and not sent is
    one he has not finished. A day he never clocked has no row and is never
    named: nothing is asked about a day nobody recorded.
    """
    row = (
        AttendanceDay.objects.filter(staff=staff, date__lt=today, submitted_at__isnull=True)
        .order_by("date")
        .first()
    )
    if row is None:
        return None
    return {"date": row.date, "state": day_state(row)}


def clock_in(worker: Staff, now: datetime) -> AttendanceData:
    """Start the worker's day at ``now``, to the minute."""
    row, created = AttendanceDay.objects.get_or_create(
        staff=worker, date=now.date(), defaults={"clock_in": _to_the_minute(now)}
    )
    if not created:
        if row.clock_out is None:
            raise ClockingRefusedError("You are already clocked in.")
        raise ClockingRefusedError(
            "You have already clocked in and out today. Change the times, or clock back in."
        )
    return attendance_data(row)


@transaction.atomic
def clock_out(worker: Staff, now: datetime) -> AttendanceData:
    """Finish the worker's day at ``now``. Only today's open day is stamped."""
    row = AttendanceDay.objects.select_for_update().filter(staff=worker, date=now.date()).first()
    if row is None:
        raise ClockingRefusedError("You are not clocked in today.")
    if row.clock_out is not None:
        raise ClockingRefusedError("You have already clocked out today.")
    finish = _to_the_minute(now)
    if finish == row.clock_in:
        # Its own words: the midnight wording below would make no sense here.
        raise ClockingRefusedError("You clocked in a moment ago. Wait a minute to clock out.")
    _require_finish_after_start(row.clock_in, finish)
    row.clock_out = finish
    row.save(update_fields=["clock_out", "updated_at"])
    generate_default_breaks(row)
    return attendance_data(row)


def _require_finish_after_start(start: time, finish: time) -> None:
    """Refuse a finish that is not later the same day; a shift past midnight is one."""
    if finish <= start:
        raise InvalidInputError(
            f"A finish time has to be later than the start time ({start:%H:%M}). "
            "If you worked past midnight, ask the office to put it right."
        )


@transaction.atomic
def set_clock_times(
    owner: Staff, day: date, start: time, finish: time | None, actor: Staff
) -> AttendanceData:
    """Set a day's clock times by hand: a forgotten tap, a correction, or a reopen.

    A worker sets their own, for any day; office staff set anyone's. No finish
    reopens the day (the person is at work again). Changing the times of a day
    that was sent un-sends it: what was sent is no longer what is recorded.
    """
    if actor.id != owner.id and not actor.is_office_staff:
        raise AccessDeniedError("Only office staff change another person's clock times.")
    if finish is not None:
        _require_finish_after_start(start, finish)
    row = AttendanceDay.objects.select_for_update().filter(staff=owner, date=day).first()
    if row is None:
        row = AttendanceDay(staff=owner, date=day)
    row.clock_in = start.replace(second=0, microsecond=0)
    row.clock_out = None if finish is None else finish.replace(second=0, microsecond=0)
    row.submitted_at = None
    row.save()
    generate_default_breaks(row)
    return attendance_data(row)


def _default_breaks() -> list[tuple[time, int, bool]]:
    """Return the workshop's standard breaks as (start, minutes, paid), from company settings.

    The one place the three settings pairs become breaks; the generator and
    its callers never name one.
    """
    company = CompanyDefaults.get_solo()
    return [
        (company.morning_break_start, company.morning_break_minutes, True),
        (company.lunch_start, company.lunch_minutes, False),
        (company.afternoon_break_start, company.afternoon_break_minutes, True),
    ]


def generate_default_breaks(row: AttendanceDay) -> None:
    """Put the workshop's usual breaks on a day, once, when it first has both times.

    A break is put in when he was there for the whole of it; a length of 0 in
    the settings means the workshop has no such break. Done once per day and
    never again: the breaks are then his, and a later correction of the clock
    times does not put back one he removed or moved. The cost, accepted by the
    owner: a day first clocked short and later corrected to a full day gets no
    breaks by itself; he or the office adds them.
    """
    if row.breaks_generated or row.clock_out is None:
        return
    for start, minutes, paid in _default_breaks():
        end_minutes = _minutes(start) + minutes
        if minutes == 0 or end_minutes > _minutes(row.clock_out) or start < row.clock_in:
            continue
        AttendanceBreak.objects.create(
            attendance_day=row,
            start=start,
            end=time(end_minutes // 60, end_minutes % 60),
            paid=paid,
        )
    row.breaks_generated = True
    row.save(update_fields=["breaks_generated", "updated_at"])


def _refuse_another_persons_day(owner_id: object, actor: Staff) -> None:
    if actor.id != owner_id and not actor.is_office_staff:
        raise AccessDeniedError("Only office staff change another person's breaks.")


def _require_break_times(start: time, end: time) -> None:
    if end <= start:
        raise InvalidInputError("A break finishes after it starts.")


@transaction.atomic
def add_break(  # noqa: PLR0913 -- a break is its day, its two times, its kind and who adds it
    owner: Staff, day: date, start: time, end: time, *, paid: bool, actor: Staff
) -> None:
    """Add a break to a day that has clock times.

    The worker's own day, or anyone's for office staff.
    """
    _refuse_another_persons_day(owner.id, actor)
    _require_break_times(start, end)
    row = AttendanceDay.objects.filter(staff=owner, date=day).first()
    if row is None:
        raise ConflictError("Set the day's clock times before adding a break.")
    AttendanceBreak.objects.create(attendance_day=row, start=start, end=end, paid=paid)


def _break_for(break_id: UUID, actor: Staff) -> AttendanceBreak:
    each = AttendanceBreak.objects.select_related("attendance_day").get(id=break_id)
    _refuse_another_persons_day(each.attendance_day.staff_id, actor)
    return each


def change_break(break_id: UUID, start: time, end: time, actor: Staff) -> None:
    """Move or resize a break. Nothing else moves, and a sent day stays sent."""
    each = _break_for(break_id, actor)
    _require_break_times(start, end)
    each.start = start
    each.end = end
    each.save(update_fields=["start", "end"])


def remove_break(break_id: UUID, actor: Staff) -> None:
    """Take a break off the day: he worked through it, or it did not happen."""
    _break_for(break_id, actor).delete()
