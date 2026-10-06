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
from apps.job.models.costing import CostLine
from apps.job.services.time_entry_rates import is_unpaid_time
from apps.timesheet.models import UNTOUCHED_STANDARD_BREAK, AttendanceDay, ClockHow
from apps.timesheet.services.location import EntryLocation, saved_remotely
from apps.timesheet.services.timesheet_events import DaySnapshot, record_day_event

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
    #: What the office is warned of about how the day was clocked, in words:
    #: "Did not clock in", "Did not clock out". Empty for times tapped at the
    #: workshop and for times the office itself set.
    cautions: list[str]


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

    #: The break's own time line. None while the break is only planned.
    id: str | None
    #: What the break is called on the screen: "Paid break", "Lunch", "Unpaid break".
    name: str
    start: time
    end: time
    #: A paid break is paid time; lunch, or an unpaid break he adds, is time
    #: logged at the unpaid rate. Lengthening one keeps its kind: an extra-long
    #: lunch is unpaid, an extra-long paid break is paid.
    paid: bool
    #: From the company's standard breaks and not yet his: shown so the day
    #: has its shape from the moment he opens it, and written by nothing.
    planned: bool
    #: A break is his time, so it waits for approval like the rest of it.
    #: None while planned.
    approved: bool | None


class StandardBreak(NamedTuple):
    """One of the workshop's standard breaks."""

    window: Window
    paid: bool
    #: What the generated line says: "Paid break" or "Lunch".
    description: str


class BreaksNotSetUpError(ConflictError):
    """The instance has no Break job, so a break cannot be recorded."""


def break_job_id() -> UUID | None:
    """Return the job every break is booked to, or None before it is set up."""
    return CompanyDefaults.get_solo().break_job_id


def _required_break_job_id() -> UUID:
    job_id = break_job_id()
    if job_id is None:
        # Refused, not skipped: a day made without its breaks would pay half
        # an hour short with nothing to show for it. In words a worker can
        # pass on; the fix is the office's (``create_shop_jobs``).
        raise BreaksNotSetUpError("Breaks are not set up. Tell the office.")
    return job_id


def _line_window(line: CostLine) -> Window | None:
    start, end = line.meta.get("start_time"), line.meta.get("end_time")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    return Window(time.fromisoformat(start), time.fromisoformat(end))


def _planned_breaks(day: date) -> list[BreakData]:
    """Return the standard day's breaks, for a day nobody has clocked.

    Shown so the day has its shape before he starts, and written by nothing
    (a GET writes nothing). Once the day has a start they are his lines.
    """
    standard = standard_day(day)
    if standard is None:
        return []
    return [
        {
            "id": None,
            "name": each.description,
            "start": each.window.start,
            "end": each.window.end,
            "paid": each.paid,
            "planned": True,
            "approved": None,
        }
        for each in _default_breaks()
        if each.window.start >= standard.start and each.window.end <= standard.end
    ]


def is_paid_break(line: CostLine) -> bool:
    """Whether a break line is a paid break rather than lunch or another unpaid break."""
    return not is_unpaid_time(line)


def day_breaks(
    day: date, row: AttendanceDay | None, break_lines: list[CostLine]
) -> list[BreakData]:
    """Return the day's breaks, paid and unpaid, in the order they happen.

    The one list, for the picture of the day and for placing entries around
    it: his lines on the Break job, which the caller already holds among the
    day's time. A day nobody has clocked shows the standard day's breaks as
    planned.
    """
    taken: list[BreakData] = []
    for line in break_lines:
        window = _line_window(line)
        if window is None:
            continue
        taken.append(
            {
                "id": str(line.id),
                "name": line.desc or ("Paid break" if is_paid_break(line) else "Unpaid break"),
                "start": window.start,
                "end": window.end,
                "paid": is_paid_break(line),
                "planned": False,
                "approved": line.approved,
            }
        )
    planned = _planned_breaks(day) if row is None else []
    return sorted([*taken, *planned], key=lambda each: (each["start"], each["end"]))


def break_windows(
    day: date, row: AttendanceDay | None, break_lines: list[CostLine]
) -> list[Window]:
    """Return every break of the day as a stretch entries are placed around."""
    return [Window(each["start"], each["end"]) for each in day_breaks(day, row, break_lines)]


def split_breaks(lines: list[CostLine]) -> tuple[list[CostLine], list[CostLine]]:
    """Split a day's time into his job entries and his breaks, in that order."""
    job_id = break_job_id()
    return (
        [line for line in lines if line.cost_set.job_id != job_id],
        [line for line in lines if line.cost_set.job_id == job_id],
    )


def duration_words(hours: Decimal) -> str:
    """Say a length of time as the screens do: "30m", "1h 15m", "2h"."""
    minutes = int((hours * 60).to_integral_value(ROUND_HALF_UP))
    whole, rest = divmod(minutes, 60)
    if whole == 0:
        return f"{rest}m"
    return f"{whole}h" if rest == 0 else f"{whole}h {rest}m"


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

    #: The clocked span less his unpaid breaks: the paid hours he was here.
    to_fill_hours: float
    #: His paid breaks: already entered for him, on the Break job.
    break_hours: float
    #: What he has entered on jobs.
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
    minutes = last - first - _minutes_inside(first, last, unpaid)
    quarters = (Decimal(minutes) / QUARTER_HOUR_MINUTES).quantize(Decimal("1"), ROUND_HALF_UP)
    return quarters * QUARTER_HOUR_MINUTES / Decimal(60)


def fill_figures(
    row: AttendanceDay | None, entered: Decimal, break_lines: list[CostLine]
) -> FillData | None:
    """Return the day's fill figures, or None until both clock times are known.

    ``entered`` is his time on jobs. Of his breaks, the paid ones count
    against the hours to fill and the screen says them apart; lunch and any
    other unpaid break come off the hours to fill, since they are not hours.
    """
    if row is None or row.clock_out is None:
        return None
    unpaid = [
        window
        for line in break_lines
        if not is_paid_break(line) and (window := _line_window(line)) is not None
    ]
    on_breaks = sum((line.quantity for line in break_lines if is_paid_break(line)), Decimal(0))
    to_fill = paid_span_hours(row.clock_in, row.clock_out, unpaid)
    return {
        "to_fill_hours": float(to_fill),
        "break_hours": float(on_breaks),
        "entered_hours": float(entered),
        "to_go_hours": float(to_fill - on_breaks - entered),
    }


def _merged(windows: list[Window]) -> list[tuple[int, int]]:
    """Return breaks as minute stretches in order, with overlapping ones joined."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted((_minutes(each.start), _minutes(each.end)) for each in windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _minutes_inside(first: int, last: int, breaks: list[Window]) -> int:
    """Return how many minutes of the breaks fall between two minutes of the day.

    Overlapping breaks count once: two that overlap are one stretch away from work.
    """
    return sum(
        max(min(last, break_end) - max(first, break_start), 0)
        for break_start, break_end in _merged(breaks)
    )


_LAST_MINUTE = 24 * 60 - 1


def finish_in_the_day(start: time, hours: Decimal, breaks: list[Window]) -> time | None:
    """Return when work of ``hours`` begun at ``start`` ends, stepping over every break.

    An entry's hours are the truth and its times are the picture (owner,
    2026-10-06): clocked in at 07:00, six hours on a job ends at 14:00, having
    stepped over two paid breaks and lunch. Breaks are outside job time, so
    none of a break is ever inside the hours. The one statement of the rule,
    for the fill sheet, an entry saved without times, an edit of its hours and
    the drawer's working out.

    None when the work would run past midnight: such hours keep no picture and
    are saved without times, never refused (hours are the truth).
    """
    cursor = _minutes(start)
    remaining = int((hours * 60).to_integral_value(ROUND_HALF_UP))
    for break_start, break_end in _merged(breaks):
        if break_end <= cursor:
            continue
        if break_start <= cursor:
            cursor = break_end
            continue
        if cursor + remaining <= break_start:
            break
        remaining -= break_start - cursor
        cursor = break_end
    finish = cursor + remaining
    if finish > _LAST_MINUTE:
        return None
    return time(finish // 60, finish % 60)


def start_after_breaks(start: time, breaks: list[Window]) -> time:
    """Return ``start``, or the end of the break it falls inside."""
    stepped = finish_in_the_day(start, Decimal(0), breaks)
    if stepped is None:
        # A break is a time of day and ends by 23:59, so this cannot be reached.
        raise ValueError(f"Stepping past the breaks from {start:%H:%M} left the day.")
    return stepped


def hours_for(start: time, finish: time, breaks: list[Window]) -> Decimal:
    """Return the hours worked between two times: the span less the breaks inside it."""
    first, last = _minutes(start), _minutes(finish)
    if last <= first:
        raise InvalidInputError("The finish has to be after the start.")
    minutes = last - first - _minutes_inside(first, last, breaks)
    return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"))


class CalendarBounds(TypedDict):
    """The stretch of the day the worker's calendar opens on."""

    start: time
    end: time


_CALENDAR_MARGIN_MINUTES = 60


#: What the calendar opens on when the day has no standard hours (a weekend).
#: A calendar matter only: it is nobody's working day.
_CALENDAR_WEEKEND_SPAN = Window(time(7, 0), time(15, 0))


def calendar_bounds(
    row: AttendanceDay | None,
    standard: Window | None,
    entry_times: list[tuple[time, time]],
) -> CalendarBounds:
    """Bound the calendar to the day, with an hour either side.

    The company's working day, stretched to the clocked span when he was
    there outside it, and to any entry outside both. The working day stays in
    view whatever he clocked: a short or odd clocking must not hide the hours
    he would tap to book.
    """
    start, finish = standard if standard is not None else _CALENDAR_WEEKEND_SPAN
    if row is not None:
        start = min(start, row.clock_in)
        finish = max(finish, row.clock_in if row.clock_out is None else row.clock_out)
    first = min([_minutes(start), *(_minutes(begin) for begin, _ in entry_times)])
    last = max([_minutes(finish), *(_minutes(end) for _, end in entry_times)])
    first = max(first - _CALENDAR_MARGIN_MINUTES, 0) // 60 * 60
    last = min(last + _CALENDAR_MARGIN_MINUTES, 24 * 60 - 1)
    return {"start": time(first // 60, first % 60), "end": time(last // 60, last % 60)}


#: The words for a start or finish the office should know about. A time
#: tapped at the workshop needs none, and neither does one the office set.
_CLOCK_IN_CAUTIONS: dict[str, str] = {
    ClockHow.NOT_CLOCKED: "Did not clock in",
    ClockHow.CLOCKED_REMOTELY: "Clocked in away from the workshop",
}
_CLOCK_OUT_CAUTIONS: dict[str, str] = {
    ClockHow.NOT_CLOCKED: "Did not clock out",
    ClockHow.CLOCKED_REMOTELY: "Clocked out away from the workshop",
}


def clock_cautions(row: AttendanceDay) -> list[str]:
    """Say, in the office's words, what was not clocked on the day."""
    cautions = []
    if row.clock_in_how in _CLOCK_IN_CAUTIONS:
        cautions.append(_CLOCK_IN_CAUTIONS[row.clock_in_how])
    if row.clock_out_how is not None and row.clock_out_how in _CLOCK_OUT_CAUTIONS:
        cautions.append(_CLOCK_OUT_CAUTIONS[row.clock_out_how])
    return cautions


def attendance_data(row: AttendanceDay | None) -> AttendanceData:
    """Shape a day's attendance, or its absence, for the wire."""
    if row is None:
        return {
            "state": "not_clocked_in",
            "clock_in": None,
            "clock_out": None,
            "here_hours": None,
            "sent_late": False,
            "cautions": [],
        }
    return {
        "state": day_state(row),
        "clock_in": row.clock_in,
        "clock_out": row.clock_out,
        "here_hours": _here_hours(row),
        "sent_late": row.submitted_at is not None
        and timezone.localdate(row.submitted_at) > row.date,
        "cautions": clock_cautions(row),
    }


def standard_day(day: date) -> Window | None:
    """Return the company's standard start and finish for the date; None on a weekend.

    The one statement of the working day. It is what a day falls back to when
    someone forgot to clock: nobody can clock in after the fact, so the
    standard hours stand in, and the office is told they were not clocked.
    """
    company = CompanyDefaults.get_solo()
    by_weekday = (
        (company.mon_start, company.mon_end),
        (company.tue_start, company.tue_end),
        (company.wed_start, company.wed_end),
        (company.thu_start, company.thu_end),
        (company.fri_start, company.fri_end),
    )
    weekday = day.weekday()
    if weekday >= len(by_weekday):
        return None
    return Window(*by_weekday[weekday])


def standard_entry_start(day: date) -> time:
    """Return where a new entry opens when the day has nothing to follow on from.

    The standard start, or on a weekend the hour the calendar opens on.
    """
    standard = standard_day(day)
    return _CALENDAR_WEEKEND_SPAN.start if standard is None else standard.start


def missed_clock_out_finish(row: AttendanceDay | None, today: date) -> time | None:
    """Return the standard finish to offer for an earlier day left clocked in, if it fits.

    None when the day is not an open earlier day, has no standard hours, or
    the standard finish is not after when he clocked in (he started at 16:00):
    then the finish is his to give.
    """
    if row is None or row.clock_out is not None or row.date >= today:
        return None
    standard = standard_day(row.date)
    if standard is None or standard.end <= row.clock_in:
        return None
    return standard.end


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


def _snapshot(row: AttendanceDay | None) -> DaySnapshot | None:
    """Read the day's clock times as a day event records them; None before the day exists."""
    if row is None:
        return None
    return {
        "clock_in": f"{row.clock_in:%H:%M}",
        "clock_out": None if row.clock_out is None else f"{row.clock_out:%H:%M}",
    }


def _record(
    actor: Staff,
    row: AttendanceDay,
    event_type: str,
    before: DaySnapshot | None,
    *,
    location: EntryLocation | None,
) -> None:
    record_day_event(
        staff=actor,
        worker=row.staff,
        day=row.date,
        event_type=event_type,
        before=before,
        after=_snapshot(row),
        trusted=not saved_remotely(actor, location),
    )


def _tapped(worker: Staff, location: EntryLocation | None) -> ClockHow:
    """How a live tap is recorded: at the workshop, or somewhere else."""
    return ClockHow.CLOCKED_REMOTELY if saved_remotely(worker, location) else ClockHow.CLOCKED


@transaction.atomic
def clock_in(worker: Staff, now: datetime, location: EntryLocation | None = None) -> AttendanceData:
    """Start the worker's day at ``now``, to the minute, judged by where his phone is."""
    row, created = AttendanceDay.objects.get_or_create(
        staff=worker,
        date=now.date(),
        defaults={"clock_in": _to_the_minute(now), "clock_in_how": _tapped(worker, location)},
    )
    if not created:
        if row.clock_out is None:
            raise ClockingRefusedError("You are already clocked in.")
        raise ClockingRefusedError(
            "You have already clocked in and out today. Change the times, or clock back in."
        )
    _record(worker, row, "clocked_in", None, location=location)
    generate_default_breaks(row, worker, location)
    return attendance_data(row)


@transaction.atomic
def clock_out(
    worker: Staff, now: datetime, location: EntryLocation | None = None
) -> AttendanceData:
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
    before = _snapshot(row)
    row.clock_out = finish
    row.clock_out_how = _tapped(worker, location)
    row.save(update_fields=["clock_out", "clock_out_how", "updated_at"])
    _record(worker, row, "clocked_out", before, location=location)
    drop_breaks_after_finish(row, worker, location)
    return attendance_data(row)


def _require_finish_after_start(start: time, finish: time) -> None:
    """Refuse a finish that is not later the same day; a shift past midnight is one."""
    if finish <= start:
        raise InvalidInputError(
            f"A finish time has to be later than the start time ({start:%H:%M}). "
            "If you worked past midnight, ask the office to put it right."
        )


def _by_hand(owner: Staff, actor: Staff) -> ClockHow:
    """How a time set by hand is recorded: the office's own entry is told apart."""
    return ClockHow.NOT_CLOCKED if actor.id == owner.id else ClockHow.SET_BY_OFFICE


@transaction.atomic
def set_clock_times(  # noqa: PLR0913 -- whose day, which day, two times, who sets them and from where
    owner: Staff,
    day: date,
    start: time,
    finish: time | None,
    actor: Staff,
    *,
    location: EntryLocation | None = None,
) -> AttendanceData:
    """Set a day's clock times by hand: a forgotten tap, a correction, or a reopen.

    A worker sets their own, for any day; office staff set anyone's. No finish
    reopens the day (the person is at work again). Changing the times of a day
    that was sent un-sends it: what was sent is no longer what is recorded.

    A time that changes stops being a tap: it is recorded as not clocked, or
    as set by the office. A time left as it was keeps how it got there, so
    correcting the finish does not disown a start he did tap.
    """
    if actor.id != owner.id and not actor.is_office_staff:
        raise AccessDeniedError("Only office staff change another person's clock times.")
    if finish is not None:
        _require_finish_after_start(start, finish)
    start = start.replace(second=0, microsecond=0)
    finish = None if finish is None else finish.replace(second=0, microsecond=0)
    by_hand = _by_hand(owner, actor)
    row = AttendanceDay.objects.select_for_update().filter(staff=owner, date=day).first()
    before = _snapshot(row)
    if row is None:
        row = AttendanceDay(staff=owner, date=day, clock_in_how=by_hand)
    elif row.clock_in != start:
        row.clock_in_how = by_hand
    if finish is None:
        row.clock_out_how = None
    elif row.clock_out != finish:
        row.clock_out_how = by_hand
    row.clock_in = start
    row.clock_out = finish
    row.submitted_at = None
    row.save()
    _record(actor, row, "clock_times_set", before, location=location)
    generate_default_breaks(row, actor, location)
    drop_breaks_after_finish(row, actor, location)
    return attendance_data(row)


@transaction.atomic
def use_standard_hours(
    owner: Staff, day: date, actor: Staff, location: EntryLocation | None = None
) -> AttendanceData:
    """Record the company's standard hours as a day nobody clocked.

    He forgot to clock and cannot go back and do it, so the standard day
    stands in and he fills it. The times are recorded as not clocked (or as
    set by the office), which is how the office is told. The usual breaks are
    put on the day as for any day with both times.
    """
    if actor.id != owner.id and not actor.is_office_staff:
        raise AccessDeniedError("Only office staff set another person's hours.")
    standard = standard_day(day)
    if standard is None:
        raise InvalidInputError("There are no standard hours on a weekend. Set the times.")
    by_hand = _by_hand(owner, actor)
    row, created = AttendanceDay.objects.get_or_create(
        staff=owner,
        date=day,
        defaults={
            "clock_in": standard.start,
            "clock_in_how": by_hand,
            "clock_out": standard.end,
            "clock_out_how": by_hand,
        },
    )
    if not created:
        raise ConflictError("This day already has clock times. Change them instead.")
    _record(actor, row, "standard_hours_used", None, location=location)
    generate_default_breaks(row, actor, location)
    drop_breaks_after_finish(row, actor, location)
    return attendance_data(row)


def _default_breaks() -> list[StandardBreak]:
    """Return the workshop's standard breaks, from company settings, in the day's order.

    The one place the three settings pairs become breaks; the generator and
    its callers never name one. A length of 0 means the workshop has no such
    break, and it is not here.
    """
    company = CompanyDefaults.get_solo()
    breaks: list[StandardBreak] = []
    for start, minutes, paid, description in (
        (company.morning_break_start, company.morning_break_minutes, True, "Paid break"),
        (company.lunch_start, company.lunch_minutes, False, "Lunch"),
        (company.afternoon_break_start, company.afternoon_break_minutes, True, "Paid break"),
    ):
        if minutes == 0:
            continue
        end = _minutes(start) + minutes
        breaks.append(StandardBreak(Window(start, time(end // 60, end % 60)), paid, description))
    return breaks


def generate_default_breaks(
    row: AttendanceDay, actor: Staff, location: EntryLocation | None = None
) -> None:
    """Put the workshop's standard breaks on a day, once, when it first has a start.

    Each standard break from his start on becomes a line on the Break job,
    saved by whoever started the day: a paid break at ordinary time, lunch at
    the unpaid rate (owner, 2026-10-06: lunch is logged, and if he worked
    through it he deletes it). From then they are his: he moves one, or
    removes it, as a line; one he adds is another break and cancels none.
    Each is marked untouched until someone edits it, so the finish can take
    away the ones he was not there for (``drop_breaks_after_finish``). His
    own wait for approval like the rest of his time; the office's start
    approved. Never marked late or remote: nobody typed them.

    Once per day and never again: a later correction of the start does not
    put back one he removed. The cost, accepted by the owner: a day first
    started late and corrected earlier gets no early breaks by itself.
    """
    if row.breaks_generated:
        return
    for each in _default_breaks():
        # A day given both times at once has no break he was not there for.
        ends_after = row.clock_out is not None and each.window.end > row.clock_out
        if each.window.start < row.clock_in or ends_after:
            continue
        _create_break(
            row.staff,
            row.date,
            each.window,
            paid=each.paid,
            description=each.description,
            actor=actor,
            location=location,
            generated=True,
        )
    row.breaks_generated = True
    row.save(update_fields=["breaks_generated", "updated_at"])


def drop_breaks_after_finish(
    row: AttendanceDay, actor: Staff, location: EntryLocation | None = None
) -> None:
    """Take off the standard breaks he was not there for, now the day has a finish.

    Only one still untouched: he left at noon, so the afternoon break goes;
    one he moved or changed is his and stays wherever it is.
    """
    if row.clock_out is None:
        return
    from apps.timesheet.services.workshop_timesheet_service import (  # noqa: PLC0415
        delete_entry,
    )

    for line in _break_lines_if_any(row.staff, row.date):
        window = _line_window(line)
        if line.meta.get("source") != UNTOUCHED_STANDARD_BREAK or window is None:
            continue
        if window.end > row.clock_out:
            delete_entry(actor, line.id, location)


def _break_lines_if_any(owner: Staff, day: date) -> list[CostLine]:
    """Return his lines on the Break job for a day; none on an instance without it."""
    job_id = break_job_id()
    if job_id is None:
        return []
    return list(
        CostLine.objects.filter(
            cost_set__kind="actual",
            kind="time",
            staff=owner,
            accounting_date=day,
            cost_set__job_id=job_id,
        ).select_related("xero_pay_item")
    )


def _create_break(  # noqa: PLR0913 -- whose break, its day and times, its kind and words, who saves it from where
    owner: Staff,
    day: date,
    window: Window,
    *,
    paid: bool,
    description: str,
    actor: Staff,
    location: EntryLocation | None,
    generated: bool,
) -> None:
    """Enter a break as what it is: a line on the Break job, paid or not, billed to nobody."""
    # Call-time import: the entry writes live in the module that reads this
    # one for the day's attendance.
    from apps.timesheet.services.workshop_timesheet_service import (  # noqa: PLC0415
        create_entry,
    )

    create_entry(
        actor,
        owner,
        {
            "job_id": _required_break_job_id(),
            "accounting_date": day,
            "hours": hours_for(window.start, window.end, []),
            "start_time": window.start,
            "end_time": window.end,
            "description": description,
            "is_billable": False,
            "wage_rate_multiplier": ORDINARY if paid else UNPAID,
        },
        location,
        generated=generated,
    )


#: The two rates a break is at: a paid break is ordinary time, lunch is unpaid.
ORDINARY = Decimal("1.0")
UNPAID = Decimal("0.0")


def _require_break_times(start: time, end: time) -> None:
    if end <= start:
        raise InvalidInputError("A break finishes after it starts.")


@transaction.atomic
def add_break(  # noqa: PLR0913 -- a break is its day, its two times, its kind and who adds it
    owner: Staff,
    day: date,
    start: time,
    end: time,
    *,
    paid: bool,
    actor: Staff,
    location: EntryLocation | None = None,
) -> None:
    """Add a break to a day that has clock times: his own, or anyone's for office staff."""
    if actor.id != owner.id and not actor.is_office_staff:
        raise AccessDeniedError("Only office staff change another person's breaks.")
    _require_break_times(start, end)
    if not AttendanceDay.objects.filter(staff=owner, date=day).exists():
        raise ConflictError("Set the day's clock times before adding a break.")
    _create_break(
        owner,
        day,
        Window(start, end),
        paid=paid,
        description="Paid break" if paid else "Unpaid break",
        actor=actor,
        location=location,
        generated=False,
    )


class BreakNotFoundError(LookupError):
    """No break has this id: it was removed, or the id names something else."""


def _break_line(break_id: UUID) -> CostLine:
    """Find a break by its line id; a line on any other job is not a break."""
    line = CostLine.objects.filter(
        id=break_id, cost_set__job_id=_required_break_job_id(), kind="time"
    ).first()
    if line is None:
        raise BreakNotFoundError(f"No break {break_id}.")
    return line


def change_break(
    break_id: UUID,
    start: time,
    end: time,
    actor: Staff,
    location: EntryLocation | None = None,
) -> None:
    """Move or resize a break. It keeps its kind: a longer lunch is longer unpaid time.

    A break is a line, so it changes as one: the same ownership, approval
    lock and audit as any of his time. Nothing else moves.
    """
    _require_break_times(start, end)
    from apps.timesheet.services.workshop_timesheet_service import (  # noqa: PLC0415
        update_entry,
    )

    update_entry(
        actor,
        {
            "entry_id": _break_line(break_id).id,
            "start_time": start,
            "end_time": end,
            "hours": hours_for(start, end, []),
        },
        location,
    )


def remove_break(break_id: UUID, actor: Staff, location: EntryLocation | None = None) -> None:
    """Take a break off the day: he worked through it, or it did not happen."""
    from apps.timesheet.services.workshop_timesheet_service import (  # noqa: PLC0415
        delete_entry,
    )

    delete_entry(actor, _break_line(break_id).id, location)
