"""Filling and sending a day (KAN-376).

A worker says what he did as rows of a job and hours, and the day is laid out
for him: the rows become entries placed one after another from where his day
has got to, each stepping over his breaks. He never works out
a start or an end time, and never adds the day up.
"""

from datetime import date, datetime, time
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.db import transaction

from apps.accounts.models import Staff
from apps.core.errors import ConflictError, InvalidInputError
from apps.job.models import Job
from apps.job.services.job_service import bills_its_time
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services import attendance
from apps.timesheet.services.attendance import Window
from apps.timesheet.services.location import EntryLocation
from apps.timesheet.services.workshop_timesheet_service import (
    WorkshopDayData,
    WorkshopEntryCreateData,
    create_entry,
    day_time_lines,
    default_entry_start,
    list_entries,
)

QUARTER_HOUR = Decimal("0.25")
TIME_AND_A_HALF = Decimal("1.5")
ORDINARY_TIME = Decimal("1.0")


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


def lay_out_rows(start: time, rows: list[FillRow], breaks: list[Window]) -> list[LaidLine]:
    """Place rows one after another from ``start``, each stepping over the breaks.

    One entry per row, never split: a row's hours are the truth and its times
    the picture, so a row that meets a break simply ends later. Rows may run
    past when he clocked out: more hours than he was here for is allowed, and
    the office sees it.
    """
    cursor = start
    lines: list[LaidLine] = []
    for row in rows:
        if row["hours"] <= 0 or row["hours"] % QUARTER_HOUR != 0:
            raise InvalidInputError("Hours are entered in quarter hours, a quarter or more.")
        # A row that would begin inside a break begins when the break ends.
        begins = attendance.finish_for(cursor, Decimal(0), breaks)
        ends = attendance.finish_for(begins, row["hours"], breaks)
        lines.append(
            {
                "job_id": row["job_id"],
                "start": begins,
                "end": ends,
                "hours": row["hours"],
                "description": row["description"],
                "time_and_a_half": row["time_and_a_half"],
            }
        )
        cursor = ends
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
    entries, break_lines = attendance.split_breaks(day_time_lines(worker, day))
    begins = default_entry_start(day, row, entries, break_lines)
    breaks = attendance.break_windows(day, row, break_lines)
    jobs = Job.objects.in_bulk({each["job_id"] for each in rows})
    for line in lay_out_rows(begins, rows, breaks):
        job = jobs.get(line["job_id"])
        if job is None:
            raise Job.DoesNotExist(f"Job {line['job_id']} does not exist.")
        data: WorkshopEntryCreateData = {
            "job_id": line["job_id"],
            "accounting_date": day,
            "hours": line["hours"],
            "start_time": line["start"],
            "end_time": line["end"],
            "wage_rate_multiplier": TIME_AND_A_HALF if line["time_and_a_half"] else ORDINARY_TIME,
            # The sheet has no billable tick: a row bills when its job can.
            # Shop and special jobs cannot, and are refused if sent as billable.
            "is_billable": bills_its_time(job),
        }
        if line["description"]:
            data["description"] = line["description"]
        create_entry(worker, worker, data, location)
    row.submitted_at = now
    row.save(update_fields=["submitted_at", "updated_at"])
    return list_entries(worker, day)
