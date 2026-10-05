"""Filling and sending a day (KAN-376).

A worker says what he did as rows of a job and hours, and the day is laid out
for him: the rows become entries placed end to end from when he clocked in,
around lunch and around anything already on his calendar. He never works out
a start or an end time, and never adds the day up.
"""

from datetime import date, datetime, time
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.db import transaction

from apps.accounts.models import Staff
from apps.core.errors import ConflictError, InvalidInputError
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services import attendance
from apps.timesheet.services.workshop_timesheet_service import (
    EntryLocation,
    WorkshopDayData,
    WorkshopEntryCreateData,
    create_entry,
    day_time_lines,
    list_entries,
    timed_span,
)

QUARTER_HOUR = Decimal("0.25")
TIME_AND_A_HALF = Decimal("1.5")
ORDINARY_TIME = Decimal("1.0")
_END_OF_DAY_MINUTES = 24 * 60 - 1


class FillRow(TypedDict):
    """One thing the worker did: a job and how long, as he would say it."""

    job_id: UUID
    hours: Decimal
    description: str | None
    #: He says so himself, as on the paper card; nothing works overtime out.
    time_and_a_half: bool


class LaidLine(TypedDict):
    """A piece of a row with its place in the day."""

    job_id: UUID
    start: time
    end: time
    hours: Decimal
    description: str | None
    time_and_a_half: bool


def _minutes(moment: time) -> int:
    return moment.hour * 60 + moment.minute


def _clock(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def lay_out_rows(
    clock_in: time, rows: list[FillRow], taken: list[tuple[time, time]]
) -> list[LaidLine]:
    """Place rows end to end from clock-in, around the stretches already taken.

    ``taken`` is lunch and every entry that already has times. A row that
    meets one is split into two lines on the same job, either side of it.
    Rows may run past when he clocked out: more hours than he was here for is
    allowed, and the office sees it.
    """
    blocks = sorted((_minutes(start), _minutes(end)) for start, end in taken)
    cursor = _minutes(clock_in)
    lines: list[LaidLine] = []
    for row in rows:
        if row["hours"] <= 0 or row["hours"] % QUARTER_HOUR != 0:
            raise InvalidInputError("Hours are entered in quarter hours, a quarter or more.")
        remaining = int(row["hours"] * 60)
        while remaining > 0:
            inside = next((end for start, end in blocks if start <= cursor < end), None)
            if inside is not None:
                cursor = inside
                continue
            next_start = min((start for start, _ in blocks if start > cursor), default=None)
            piece = remaining if next_start is None else min(remaining, next_start - cursor)
            if cursor + piece > _END_OF_DAY_MINUTES:
                raise InvalidInputError(
                    "These hours run past midnight. Ask the office to enter this day."
                )
            lines.append(
                {
                    "job_id": row["job_id"],
                    "start": _clock(cursor),
                    "end": _clock(cursor + piece),
                    "hours": Decimal(piece) / Decimal(60),
                    "description": row["description"],
                    "time_and_a_half": row["time_and_a_half"],
                }
            )
            cursor += piece
            remaining -= piece
    return lines


@transaction.atomic
def submit_day(
    worker: Staff,
    day: date,
    rows: list[FillRow],
    location: EntryLocation | None,
    now: datetime,
) -> WorkshopDayData:
    """Save the worker's rows as entries and send the day to the office.

    All or nothing: a row that cannot be saved leaves the day as it was and
    unsent. Sending with hours still to go is allowed; attendance binds
    nothing and the office sees the gap. ``location`` is where his phone says
    it is, passed to every entry so each is judged, not assumed away.
    """
    row = AttendanceDay.objects.select_for_update().filter(staff=worker, date=day).first()
    if row is None or row.clock_out is None:
        raise ConflictError("Clock out before you send the day.")
    taken = [span for line in day_time_lines(worker, day) if (span := timed_span(line))]
    lunch = attendance.lunch_window(row)
    if lunch is not None:
        taken.append((lunch.start, lunch.end))
    for line in lay_out_rows(row.clock_in, rows, taken):
        data: WorkshopEntryCreateData = {
            "job_id": line["job_id"],
            "accounting_date": day,
            "hours": line["hours"],
            "start_time": line["start"],
            "end_time": line["end"],
            "wage_rate_multiplier": TIME_AND_A_HALF if line["time_and_a_half"] else ORDINARY_TIME,
        }
        if line["description"]:
            data["description"] = line["description"]
        create_entry(worker, worker, data, location)
    row.submitted_at = now
    row.save(update_fields=["submitted_at", "updated_at"])
    return list_entries(worker, day)
