"""What the customer is billed and the worker paid for an entry (owner, 2026-10-25).

An entry's hours are its start to stop less the breaks inside it; a break
added, moved or taken off re-works the entries around it; the hours past the
usual day are time and a half by default, charged so too.
"""

from datetime import time, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.services import attendance, workshop_timesheet_service
from apps.timesheet.tests.conftest import WEEK_START

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]

DAY = WEEK_START
SATURDAY = WEEK_START + timedelta(days=5)
DAY_URL = "/api/job/workshop/timesheets/"
PLACEMENT_URL = "/api/timesheets/my-day/placement/"


def _book(worker: Staff, job: Job, start: str, end: str, *, rate: str = "1.0") -> None:
    """Book a job as the drawer does: the hours are the placement rule's answer."""
    hours = attendance.hours_for(
        time.fromisoformat(start),
        time.fromisoformat(end),
        workshop_timesheet_service.day_break_windows(worker, DAY),
    )
    workshop_timesheet_service.create_entry(
        worker,
        worker,
        {
            "job_id": job.id,
            "accounting_date": DAY,
            "hours": hours,
            "start_time": time.fromisoformat(start),
            "end_time": time.fromisoformat(end),
            "wage_rate_multiplier": Decimal(rate),
        },
    )


def _on(job: Job, worker: Staff) -> list[tuple[str, str, Decimal, float]]:
    """The job's lines for him: start, stop, hours and pay rate, in the order made."""
    return [
        (
            line.meta["start_time"],
            line.meta["end_time"],
            line.quantity,
            line.meta["wage_rate_multiplier"],
        )
        for line in CostLine.objects.filter(staff=worker, cost_set__job=job).order_by("created_at")
    ]


def _break_at(worker: Staff, start: time) -> UUID:
    """The id of his break that starts at ``start``; a planned one has none."""
    ids = [
        each["id"]
        for each in workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        if each["start"] == start
    ]
    assert len(ids) == 1, ids
    assert ids[0] is not None, f"The {start:%H:%M} break is only planned"
    return UUID(ids[0])


class TestBreaksAndEntries:
    """Breaks come first, like the start time, and never change an entry (owner, 2026-10-25)."""

    def _morning(self, worker: Staff) -> None:
        """Clocked in at 07:00, on break 07:30-08:00: the owner's example day, before any entry."""
        attendance.set_clock_times(worker, DAY, time(7, 0), time(15, 0), worker)
        attendance.remove_break(_break_at(worker, time(8, 30)), worker)
        attendance.add_break(worker, DAY, time(7, 30), time(8, 0), paid=True, actor=worker)

    def test_the_customer_is_billed_for_the_time_on_the_job(self, worker: Staff, job: Job) -> None:
        """Guards attendance.hours_for: 07:00-09:00 less the 07:30 break is 1.5h on the job."""
        self._morning(worker)

        _book(worker, job, "07:00", "09:00")

        assert _on(job, worker) == [("07:00:00", "09:00:00", Decimal("1.500"), 1.0)]

    def test_changing_or_deleting_a_break_never_changes_an_entry(
        self, worker: Staff, job: Job
    ) -> None:
        """He worked through part of his break and edits it: his entry stands as entered.

        Guards workshop_timesheet_service.update_entry and delete_entry: a break
        line's change touches no other line. Changing the entry is his own edit.
        """
        self._morning(worker)
        _book(worker, job, "07:00", "09:00")

        attendance.change_break(_break_at(worker, time(7, 30)), time(7, 30), time(7, 45), worker)
        shortened = _on(job, worker)
        attendance.remove_break(_break_at(worker, time(7, 30)), worker)

        assert shortened == [("07:00:00", "09:00:00", Decimal("1.500"), 1.0)]
        assert _on(job, worker) == [("07:00:00", "09:00:00", Decimal("1.500"), 1.0)]

    def test_a_break_he_adds_over_his_entry_changes_nothing_else(
        self, worker: Staff, job: Job
    ) -> None:
        """He says "actually I took a break at 09:30": the break is his to add; the entry stands.

        Guards attendance.add_break: a break written onto a day touches no entry.
        """
        self._morning(worker)
        _book(worker, job, "09:00", "10:00")

        attendance.add_break(worker, DAY, time(9, 30), time(9, 45), paid=True, actor=worker)

        assert _on(job, worker) == [("09:00:00", "10:00:00", Decimal("1.000"), 1.0)]
        assert time(9, 30) in [
            each["start"] for each in workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        ]

    def test_a_standard_break_is_not_recorded_inside_an_hour_with_no_room_for_it(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """The bug PR #228 began with: 08:00-09:00 booked as 1h, then the day got its breaks.

        Guards attendance.generate_default_breaks: the system puts a standard
        break only where it fits. A whole hour has no room for the 08:30 break,
        so it is skipped and the hour is paid once; lunch and 13:30 go on.
        """
        workshop_timesheet_service.create_entry(
            worker,
            worker,
            {
                "job_id": job.id,
                "accounting_date": DAY,
                "hours": Decimal("1"),
                "start_time": time(8, 0),
                "end_time": time(9, 0),
            },
        )

        attendance.use_standard_hours(worker, DAY, office_staff)

        assert _on(job, worker) == [("08:00:00", "09:00:00", Decimal("1.000"), 1.0)]
        assert [
            (each["start"], each["end"])
            for each in workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        ] == [(time(11, 30), time(12, 0)), (time(13, 30), time(13, 45))]

    def test_a_standard_break_is_recorded_where_the_entry_was_placed_around_it(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """Four hours from 07:00 on a day nobody clocked run to 11:15 around the planned 08:30.

        Guards attendance.generate_default_breaks: that entry has room for the
        break (255 minutes less 15 is its 4h), so the paid break is recorded
        and not lost when the day gets its times.
        """
        workshop_timesheet_service.create_entry(
            worker, worker, {"job_id": job.id, "accounting_date": DAY, "hours": Decimal("4")}
        )

        attendance.use_standard_hours(worker, DAY, office_staff)

        assert _on(job, worker) == [("07:00:00", "11:15:00", Decimal("4.000"), 1.0)]
        assert [
            (each["start"], each["paid"])
            for each in workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        ] == [(time(8, 30), True), (time(11, 30), False), (time(13, 30), True)]


class TestHoursPastTheUsualDay:
    """Guards workshop_timesheet_service.overtime_hours and _split_at_overtime."""

    def test_a_long_day_on_one_job_is_eight_ordinary_hours_then_time_and_a_half(
        self, worker_client: Client, worker: Staff, job: Job
    ) -> None:
        """07:00-17:00 with the three standard breaks inside: 9h on the job, 1h past 8."""
        attendance.set_clock_times(worker, DAY, time(7, 0), time(17, 0), worker)
        asked = worker_client.get(
            f"{PLACEMENT_URL}?date={DAY.isoformat()}&start=07:00&finish=17:00"
        ).json()

        _book(worker, job, "07:00", "17:00")

        assert (asked["hours"], asked["overtime_hours"]) == (9.0, 1.0)
        assert _on(job, worker) == [
            ("07:00:00", "16:00:00", Decimal("8.000"), 1.0),
            ("16:00:00", "17:00:00", Decimal("1.000"), 1.5),
        ]
        ordinary, late = CostLine.objects.filter(staff=worker, cost_set__job=job).order_by(
            "created_at"
        )
        # Paid and, by default, charged at time and a half.
        assert late.unit_cost == ordinary.unit_cost * Decimal("1.5")
        assert late.unit_rev == ordinary.unit_rev * Decimal("1.5")

    def test_a_rate_he_chose_stands(self, worker: Staff, job: Job) -> None:
        attendance.set_clock_times(worker, DAY, time(7, 0), time(17, 0), worker)

        _book(worker, job, "07:00", "17:00", rate="2.0")

        assert _on(job, worker) == [("07:00:00", "17:00:00", Decimal("9.000"), 2.0)]

    def test_an_edit_that_adds_hours_does_not_re_rate(self, worker: Staff, job: Job) -> None:
        attendance.set_clock_times(worker, DAY, time(7, 0), time(17, 0), worker)
        _book(worker, job, "07:00", "11:15")
        line = CostLine.objects.get(staff=worker, cost_set__job=job)

        workshop_timesheet_service.update_entry(
            worker, {"entry_id": line.id, "hours": Decimal("9")}
        )

        assert _on(job, worker) == [("07:00:00", "17:00:00", Decimal("9.000"), 1.0)]

    def test_a_weekend_has_no_usual_day(self, worker: Staff, job: Job) -> None:
        workshop_timesheet_service.create_entry(
            worker,
            worker,
            {"job_id": job.id, "accounting_date": SATURDAY, "hours": Decimal("10")},
        )

        rates = CostLine.objects.filter(staff=worker, cost_set__job=job).values_list(
            "quantity", "meta__wage_rate_multiplier"
        )
        assert list(rates) == [(Decimal("10.000"), 1.0)]
