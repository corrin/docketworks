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

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.errors import AccessDeniedError, ConflictError, InvalidInputError
from apps.timesheet.models import AttendanceDay

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


class LunchWindow(NamedTuple):
    """The unpaid break inside a clocked day."""

    start: time
    end: time


def lunch_window(row: AttendanceDay | None) -> LunchWindow | None:
    """Return the day's unpaid lunch break, or None when the day has none.

    The one source of a day's lunch: the hours to fill, the layout of filled
    rows, the day read and the calendar all ask here and nowhere else.

    Fable: How lunch is stored is with the owner (KAN-376, 2026-10-06), so
    until that is ruled no day has one. The settings that say when lunch is
    (``CompanyDefaults.lunch_start`` / ``lunch_minutes``) are already in.
    """
    del row
    return None


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


def paid_span_hours(start: time, finish: time, lunch: LunchWindow | None) -> Decimal:
    """Hours between two clock times less lunch, to the nearest quarter hour.

    Entries are in quarter hours and a real clock is not (06:28 to 15:04), so
    the span is rounded once here and nothing downstream shows "0.1 to go".
    """
    minutes = _minutes(finish) - _minutes(start)
    if lunch is not None:
        minutes -= _minutes(lunch.end) - _minutes(lunch.start)
    quarters = (Decimal(minutes) / QUARTER_HOUR_MINUTES).quantize(Decimal("1"), ROUND_HALF_UP)
    return quarters * QUARTER_HOUR_MINUTES / Decimal(60)


def fill_figures(
    row: AttendanceDay | None, lunch: LunchWindow | None, entered: Decimal
) -> FillData | None:
    """Return the day's fill figures, or None until both clock times are known."""
    if row is None or row.clock_out is None:
        return None
    to_fill = paid_span_hours(row.clock_in, row.clock_out, lunch)
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
    """Bound the calendar to the day as it happened, with an hour either side.

    The clocked span when there is one (an open day runs to the working day's
    end), else the company's working day; widened to hold any entry outside.
    """
    start, finish = working_day
    if row is not None:
        start = row.clock_in
        finish = max(finish, row.clock_in) if row.clock_out is None else row.clock_out
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
    return attendance_data(row)
