"""Clocking in and out: when a person was at work on a day (KAN-376).

It helps the worker and the office see the day, and binds nothing: no pay,
no approval and no entry depends on it. Every function is told the time
(``now``) by its caller, so nothing here reads the clock.

Refusals are raised here, as typed errors a person can read. The table's
constraints state the same facts about a row and are the backstop, never the
message.
"""

from datetime import date, datetime, time
from typing import Literal, TypedDict

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


def pending_date(staff: Staff, today: date) -> date | None:
    """Return the earliest earlier day this person is still clocked in on, if any.

    A day left open cannot be closed by a tap on a later date: the finish time
    is not known, so it is asked for.
    """
    return (
        AttendanceDay.objects.filter(staff=staff, date__lt=today, clock_out__isnull=True)
        .order_by("date")
        .values_list("date", flat=True)
        .first()
    )


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
