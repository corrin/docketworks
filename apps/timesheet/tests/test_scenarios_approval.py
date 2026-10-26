"""Approval, changes after it, clocks and dates, races, staff and job changes (plan 2026-10-25).

One test per scenario in the owner's list, named by its id. Each day is set up
through the services the screens call; ``make_time_line`` and the invoice and
quote factories stand in only for things made elsewhere, and say so. Every
expected number is worked out by hand in the comments beside it.

The company's default day in these tests: 07:00 to 15:00, a paid break
08:30-08:45, unpaid lunch 11:30-12:00 and a paid break 13:30-13:45. The
worker's wage is 48.00 an hour (40.00 base plus the 20% loading); the job
charges 120.00.

Xero posting (T1-T4, J1, C5, S5, N6) lives in apps/xero/tests/test_scenarios_posting.py:
the layer contract forbids apps.timesheet importing apps.xero.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client
from django.utils import timezone

from apps.accounting.services.invoice_calculation import get_job_invoicing_basis
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_invoice, make_job, make_material_line
from apps.core.errors import InvalidInputError
from apps.core.models import CompanyDefaults
from apps.core.tests.concurrency import await_database_lock, start_database_task
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.job.services.job_service import CostLineWriteData, create_cost_line
from apps.timesheet.models import AttendanceDay, TimesheetEvent
from apps.timesheet.services import (
    approval,
    attendance,
    day_submission,
    hour_categories,
    workshop_timesheet_service,
)
from apps.timesheet.services.approval import StaffApprovalData
from apps.timesheet.services.timesheet_entry_options import get_jobs_for_entry
from apps.timesheet.services.weekly_timesheet_service import payroll_week_start
from apps.timesheet.services.workshop_timesheet_service import (
    WorkshopEntryCreateData,
    WorkshopEntryData,
    WorkshopWeekData,
)
from apps.timesheet.tests.conftest import WEEK_START, authenticated_client, make_staff

#: A Monday in May 2026, long gone, so every service treats it as a day worked.
DAY = WEEK_START
SUNDAY_BEFORE = WEEK_START - timedelta(days=1)
WEDNESDAY = WEEK_START + timedelta(days=2)
THURSDAY = WEEK_START + timedelta(days=3)
FRIDAY = WEEK_START + timedelta(days=4)
PLACEMENT_URL = "/api/timesheets/my-day/placement/"
APPROVE_LINE_URL = "/api/job/cost_lines/{line_id}/approve/"
APPROVE_DAY_URL = "/api/timesheets/approvals/{staff_id}/{day}/approve/"
BACKWARDS_REFUSAL = "The finish time must be after the start time."

DATABASE = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]
COMMITTED = [pytest.mark.committed_db, pytest.mark.usefixtures("break_job")]


def at(hour: int, minute: int = 0) -> time:
    return time(hour, minute)


def exactly(message: str) -> str:
    """A ``pytest.raises`` pattern matching the whole message and nothing else."""
    return f"^{re.escape(message)}$"


@pytest.fixture
def general_work(superuser: Staff) -> Job:
    """The internal job the sweep books to, as ``create_shop_jobs`` leaves it."""
    defaults = CompanyDefaults.get_solo()
    job = make_job(defaults.shop_company, superuser, name="General work", status="special")
    defaults.general_work_job = job
    defaults.save(update_fields=["general_work_job"])
    return job


@pytest.fixture
def company_address() -> None:
    """Give the company the geocoded address a phone's location is compared against."""
    defaults = CompanyDefaults.get_solo()
    defaults.latitude = Decimal("-36.9220862")
    defaults.longitude = Decimal("174.8000000")
    defaults.save(update_fields=["latitude", "longitude"])


def _book(  # noqa: PLR0913 -- an entry as the drawer saves it: who, whose, where, when, and its billing
    actor: Staff,
    owner: Staff,
    job: Job,
    start: time,
    end: time,
    *,
    day: date = DAY,
    is_billable: bool = True,
    wage_rate_multiplier: Decimal = Decimal("1.0"),
) -> WorkshopEntryData:
    """Save an entry with a start and stop; its hours are the placement rule's answer."""
    hours = attendance.hours_for(
        start, end, workshop_timesheet_service.day_break_windows(owner, day)
    )
    data: WorkshopEntryCreateData = {
        "job_id": job.id,
        "accounting_date": day,
        "hours": hours,
        "start_time": start,
        "end_time": end,
        "is_billable": is_billable,
        "wage_rate_multiplier": wage_rate_multiplier,
    }
    return workshop_timesheet_service.create_entry(actor, owner, data)


def _untimed(
    actor: Staff, owner: Staff, job: Job, hours: str, *, day: date = DAY
) -> WorkshopEntryData:
    """Save an entry given hours alone, as the drawer does when no start is typed."""
    data: WorkshopEntryCreateData = {
        "job_id": job.id,
        "accounting_date": day,
        "hours": Decimal(hours),
    }
    return workshop_timesheet_service.create_entry(actor, owner, data)


def _line(entry: WorkshopEntryData) -> CostLine:
    return CostLine.objects.get(id=UUID(entry["id"]))


def _lines(job: Job, worker: Staff) -> list[CostLine]:
    """His lines on the job, in the order they were made."""
    return list(CostLine.objects.filter(cost_set__job=job, staff=worker).order_by("entry_seq"))


def _total(lines: list[CostLine]) -> Decimal:
    return sum((line.quantity for line in lines), Decimal(0))


def _hours_by_rate(job: Job, worker: Staff) -> dict[float, Decimal]:
    """His hours on the job, summed by the wage multiplier each line is paid at."""
    totals: defaultdict[float, Decimal] = defaultdict(Decimal)
    for line in _lines(job, worker):
        totals[float(hour_categories.wage_rate_multiplier(line))] += line.quantity
    return dict(totals)


def _week(worker: Staff, day: date = DAY) -> WorkshopWeekData:
    """The payroll week's approved hours (what payroll pays) and waiting hours."""
    return workshop_timesheet_service.list_entries(worker, day)["week"]


def _row(worker: Staff, day: date = DAY) -> StaffApprovalData:
    """His row on the Approve time screen."""
    [row] = [
        row for row in approval.day_approvals(day)["staff"] if row["staff_id"] == str(worker.id)
    ]
    return row


def _swept(general_work: Job, worker: Staff) -> list[tuple[str, str, Decimal]]:
    """Each swept General work entry as (start, stop, hours), in the order of the day."""
    return sorted(
        (str(line.meta["start_time"]), str(line.meta["end_time"]), line.quantity)
        for line in CostLine.objects.filter(cost_set__job=general_work, staff=worker)
    )


def _summary(job: Job) -> dict[str, float]:
    """The job's actual cost, revenue and hours, as the costing screens read them."""
    summary = Job.objects.get(pk=job.pk).latest_actual.summary
    return {key: float(summary[key]) for key in ("cost", "rev", "hours")}


#: The standard day the sweep books for nobody clocking, around its breaks:
#: 07:00-08:30, 08:45-11:30, 12:00-13:30, 13:45-15:00.
STANDARD_SWEEP = [
    ("07:00:00", "08:30:00", Decimal("1.500")),
    ("08:45:00", "11:30:00", Decimal("2.750")),
    ("12:00:00", "13:30:00", Decimal("1.500")),
    ("13:45:00", "15:00:00", Decimal("1.250")),
]


@pytest.mark.usefixtures("general_work")
class TestChangesAfterApproval:
    pytestmark = DATABASE

    def test_c1_an_entry_added_after_approval_waits_and_the_approved_entries_stand(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """The office approved his day; the next day he adds a 2h entry to it.

        The new entry is waiting (unpaid until approved) and the day shows
        something waiting. The approved entries are untouched.

        Guards workshop_timesheet_service._save_entry and approval._staff_day.
        """
        attendance.set_clock_times(worker, DAY, at(7), at(15), worker)
        # 07:00-11:00 less the 08:30-08:45 break: 3.75h.
        morning = _book(worker, worker, job, at(7), at(11))
        approval.approve_day(worker, DAY, office_staff)

        later = _untimed(worker, worker, job, "2")

        assert (_line(morning).quantity, _line(morning).approved) == (Decimal("3.750"), True)
        assert (_line(later).quantity, _line(later).approved) == (Decimal("2.000"), False)
        row = _row(worker)
        assert (row["state"], row["waiting_hours"]) == ("waiting", 2.0)

    def test_c2_job_x_typed_on_a_swept_day_takes_its_time_from_the_general_work(
        self, office_staff: Staff, worker: Staff, job: Job, general_work: Job
    ) -> None:
        """Swept, then he adds Job X 09:00-11:00: General work is the rest of the day.

        Owner, 2026-10-26: General work is "like a bit flag": "any time that
        isn't on a job or break is general work", so it shrinks round X by
        itself. X is 2h at the ordinary rate: General work is not time X comes
        after. The General work that changed waits for approval, as any change.

        Guards workshop_timesheet_service.refill_general_work and overtime_hours.
        """
        approval.sweep_person(worker, [DAY], office_staff)

        _book(worker, worker, job, at(9), at(11))

        assert _swept(general_work, worker) == [
            ("07:00:00", "08:30:00", Decimal("1.500")),
            ("08:45:00", "09:00:00", Decimal("0.250")),
            ("11:00:00", "11:30:00", Decimal("0.500")),
            ("12:00:00", "13:30:00", Decimal("1.500")),
            ("13:45:00", "15:00:00", Decimal("1.250")),
        ]
        assert _hours_by_rate(job, worker) == {1.0: Decimal("2.000")}
        # Approved: the paid breaks, 0.5h. Waiting: X 2h and the General work 5h.
        assert _week(worker) == {"approved_hours": 0.5, "waiting_hours": 7.0}

        approval.approve_day(worker, DAY, office_staff)

        # Paid once: General work 5h + X 2h + paid breaks 0.5h = 7.5h.
        assert _week(worker) == {"approved_hours": 7.5, "waiting_hours": 0.0}

    def test_c2_hours_alone_on_a_swept_day_go_in_from_the_start_of_the_day(
        self, office_staff: Staff, worker: Staff, job: Job, general_work: Job
    ) -> None:
        """Swept, then he says "2h on Job X" with no times, as he enters nearly everything.

        General work is filler, so X goes at the day's first time not on a job:
        07:00, round the 08:30 break to 09:15. After the General work, from
        15:00, all of it would have been overtime.

        Guards workshop_timesheet_service.next_entry_start (General work is free time).
        """
        approval.sweep_person(worker, [DAY], office_staff)

        _untimed(worker, worker, job, "2")

        [x] = _lines(job, worker)
        assert (x.meta["start_time"], x.meta["end_time"], x.quantity) == (
            "07:00:00",
            "09:15:00",
            Decimal("2.000"),
        )
        assert _hours_by_rate(job, worker) == {1.0: Decimal("2.000")}
        assert _swept(general_work, worker) == [
            ("09:15:00", "11:30:00", Decimal("2.250")),
            ("12:00:00", "13:30:00", Decimal("1.500")),
            ("13:45:00", "15:00:00", Decimal("1.250")),
        ]

    def test_c2_deleting_his_entry_gives_the_time_back_to_general_work(
        self, office_staff: Staff, worker: Staff, job: Job, general_work: Job
    ) -> None:
        """Guards workshop_timesheet_service.delete_entry (the day refills)."""
        approval.sweep_person(worker, [DAY], office_staff)
        x = _untimed(worker, worker, job, "2")

        workshop_timesheet_service.delete_entry(worker, UUID(x["id"]))

        assert _swept(general_work, worker) == STANDARD_SWEEP

    def test_c2_a_long_swept_day_puts_the_overtime_on_the_general_work(
        self, office_staff: Staff, worker: Staff, job: Job, general_work: Job
    ) -> None:
        """Clocked 07:00-17:00 and swept, then 2h on a job: the job stays ordinary.

        07:00-17:00 less the three breaks is 9h: 2h on the job, 7h General
        work, made after it, so the hour past the usual 8 is General work's.

        Guards workshop_timesheet_service.refill_general_work (General work is made last).
        """
        attendance.set_clock_times(worker, DAY, at(7), at(17), worker)
        approval.sweep_person(worker, [DAY], office_staff)

        _untimed(worker, worker, job, "2")

        assert _hours_by_rate(job, worker) == {1.0: Decimal("2.000")}
        assert _hours_by_rate(general_work, worker) == {
            1.0: Decimal("6.000"),
            1.5: Decimal("1.000"),
        }

    def test_c2_a_break_added_on_a_swept_day_takes_its_time_from_the_general_work(
        self, office_staff: Staff, worker: Staff, general_work: Job
    ) -> None:
        """Guards attendance.add_break (the day refills round the break)."""
        approval.sweep_person(worker, [DAY], office_staff)

        attendance.add_break(worker, DAY, at(10), at(10, 15), paid=True, actor=worker)

        assert _swept(general_work, worker) == [
            ("07:00:00", "08:30:00", Decimal("1.500")),
            ("08:45:00", "10:00:00", Decimal("1.250")),
            ("10:15:00", "11:30:00", Decimal("1.250")),
            ("12:00:00", "13:30:00", Decimal("1.500")),
            ("13:45:00", "15:00:00", Decimal("1.250")),
        ]

    def test_c2_deleting_general_work_turns_it_off_for_the_day_and_a_sweep_turns_it_on(
        self, office_staff: Staff, worker: Staff, general_work: Job
    ) -> None:
        """Deleting one General work line takes the day's General work off, all of it.

        A refill would put a single deleted line straight back.

        Guards workshop_timesheet_service.delete_entry (a General work line clears the flag).
        """
        approval.sweep_person(worker, [DAY], office_staff)
        first = CostLine.objects.filter(cost_set__job=general_work, staff=worker).first()
        assert first is not None

        workshop_timesheet_service.delete_entry(office_staff, first.id)

        assert _swept(general_work, worker) == []
        assert AttendanceDay.objects.get(staff=worker, date=DAY).general_work_fill is False
        assert list(
            TimesheetEvent.objects.filter(worker=worker, event_type__startswith="general_work")
            .order_by("timestamp")
            .values_list("event_type", flat=True)
        ) == ["general_work_on", "general_work_off"]

        approval.sweep_person(worker, [DAY], office_staff)

        assert _swept(general_work, worker) == STANDARD_SWEEP

    def test_c2_general_work_times_are_not_edited_by_hand(
        self, office_staff: Staff, worker: Staff, general_work: Job
    ) -> None:
        """Guards workshop_timesheet_service.update_entry (General work is the rest of the day)."""
        approval.sweep_person(worker, [DAY], office_staff)
        first = CostLine.objects.filter(cost_set__job=general_work, staff=worker).first()
        assert first is not None

        with pytest.raises(InvalidInputError, match="General work fills the time"):
            workshop_timesheet_service.update_entry(
                office_staff, {"entry_id": first.id, "end_time": at(8)}
            )

    def test_c2_placement_on_a_swept_day_starts_at_the_start_of_the_day(
        self, office_staff: Staff, worker: Staff, worker_client: Client
    ) -> None:
        """Guards the placement endpoint: General work is free time, and never counts to 8h."""
        approval.sweep_person(worker, [DAY], office_staff)

        answer = worker_client.get(
            f"/api/timesheets/my-day/placement/?date={DAY.isoformat()}&hours=2"
        ).json()

        assert (answer["start"], answer["finish"], answer["overtime_hours"]) == (
            "07:00:00",
            "09:15:00",
            0.0,
        )

    def test_c3_he_edits_or_deletes_his_approved_entry_and_the_office_checks_it_again(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """He changes an entry the office approved: saved, and it waits for the office again.

        Owner, 2026-10-26: "OFFICE HAS LESS AUTHORTITY TO CHANGE TIME SHEETS
        THAN STAFF." Approval is the office checking the entry, and his change
        has not been checked. The approved flag follows the audit log: the
        edit's own event records approved going from true to false.

        Guards workshop_timesheet_service.update_entry and delete_entry.
        """
        entry = _book(worker, worker, job, at(9), at(11))
        other = _book(worker, worker, job, at(12), at(13))
        approval.approve_day(worker, DAY, office_staff)
        entry_id = UUID(entry["id"])

        workshop_timesheet_service.update_entry(
            worker, {"entry_id": entry_id, "hours": Decimal("1")}
        )
        workshop_timesheet_service.delete_entry(worker, UUID(other["id"]))

        line = _line(entry)
        assert (line.quantity, line.approved) == (Decimal("1.000"), False)
        edit = TimesheetEvent.objects.filter(cost_line_id=line.id, event_type="entry_updated").get()
        assert edit.staff_id == worker.id
        assert edit.delta_before is not None
        assert edit.delta_after is not None
        assert (edit.delta_before["approved"], edit.delta_after["approved"]) == (True, False)
        assert not CostLine.objects.filter(id=UUID(other["id"])).exists()

    def test_c4_the_office_edits_an_approved_entry_and_approves_it_again_after(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """The office edits an approved entry: saved and audited, and it waits to be approved.

        Owner, 2026-10-26: "The office entering time and the office approving
        time are different operations. Just because the same person can do
        both, doesn't reduce it to one operation."

        Guards workshop_timesheet_service.update_entry (a change takes the approval off).
        """
        entry = _book(worker, worker, job, at(9), at(11))
        approval.approve_day(worker, DAY, office_staff)

        workshop_timesheet_service.update_entry(
            office_staff, {"entry_id": UUID(entry["id"]), "hours": Decimal("1.5")}
        )

        line = _line(entry)
        assert (line.quantity, line.approved) == (Decimal("1.500"), False)
        # 1.5h at 48.00 = 72.00 paid, at 120.00 = 180.00 billed.
        assert (line.total_cost, line.total_rev) == (Decimal("72.00"), Decimal("180.00"))
        [edited] = TimesheetEvent.objects.filter(cost_line_id=line.id, event_type="entry_updated")
        assert edited.staff_id == office_staff.id
        assert approval.approve_day(worker, DAY, office_staff) == 1
        assert _line(entry).approved is True

    def test_c6_changing_a_sent_days_clock_times_unsends_it(self, worker: Staff) -> None:
        """He changes a sent day's clock times: the day is no longer sent.

        Guards attendance.set_clock_times.
        """
        attendance.set_clock_times(worker, DAY, at(7), at(15), worker)
        day_submission.submit_day(worker, DAY, [], None, timezone.now())
        assert workshop_timesheet_service.list_entries(worker, DAY)["day"]["state"] == "sent"

        attendance.set_clock_times(worker, DAY, at(7), at(14), worker)

        assert workshop_timesheet_service.list_entries(worker, DAY)["day"]["state"] == (
            "clocked_out"
        )
        assert AttendanceDay.objects.get(staff=worker, date=DAY).submitted_at is None

    def test_c7_a_break_he_adds_to_an_approved_day_waits_and_changes_nothing_approved(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """He adds a break to a day whose entries the office already approved.

        He may enter whatever he likes; the office checks it (owner, 2026-10-25).
        The break is new time, so it waits for the office; the approved entry
        under it stands exactly as approved, since a break never changes an entry.

        Guards attendance.add_break and approval._waiting.
        """
        attendance.set_clock_times(worker, DAY, at(7), at(15), worker)
        entry = _book(worker, worker, job, at(9), at(11))
        approval.approve_day(worker, DAY, office_staff)

        attendance.add_break(worker, DAY, at(9, 30), at(9, 45), paid=True, actor=worker)

        line = _line(entry)
        # 09:00-11:00 holds no standard break: 2h, as approved.
        assert (line.quantity, line.approved) == (Decimal("2.000"), True)
        assert _row(worker)["state"] == "waiting"

    def test_c8_general_work_the_office_deletes_is_booked_again_by_a_re_sweep(
        self, office_staff: Staff, worker: Staff, general_work: Job
    ) -> None:
        """The office deletes the General work the sweep made.

        One line deleted is the day's fill turned off (owner, 2026-10-26: the
        flag is the truth): the time is unbooked, all of it, and a re-sweep
        books it again. Audited.

        Guards approval._sweep and workshop_timesheet_service.delete_entry.
        """
        approval.sweep_person(worker, [DAY], office_staff)
        [mid_morning] = [
            line
            for line in CostLine.objects.filter(cost_set__job=general_work, staff=worker)
            if line.meta["start_time"] == "08:45:00"
        ]

        workshop_timesheet_service.delete_entry(office_staff, mid_morning.id)

        assert _swept(general_work, worker) == []
        [deleted] = TimesheetEvent.objects.filter(
            cost_line_id=mid_morning.id, event_type="entry_deleted"
        )
        assert deleted.staff_id == office_staff.id

        approval.sweep_person(worker, [DAY], office_staff)

        assert _swept(general_work, worker) == STANDARD_SWEEP


class TestApprovalHairyCases:
    pytestmark = DATABASE

    def test_s1_he_deletes_a_waiting_entry_after_the_rest_was_approved(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """He deletes his waiting entry after the office approved the rest of the day.

        Allowed. Approved entries are untouched.

        Guards workshop_timesheet_service.delete_entry.
        """
        approved = _book(worker, worker, job, at(7), at(8))
        approval.approve_day(worker, DAY, office_staff)
        waiting = _book(worker, worker, job, at(9), at(10))

        workshop_timesheet_service.delete_entry(worker, UUID(waiting["id"]))

        assert not CostLine.objects.filter(id=UUID(waiting["id"])).exists()
        line = _line(approved)
        assert (line.quantity, line.approved) == (Decimal("1.000"), True)

    def test_s2_one_entry_approved_alone_is_the_only_one_paid(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """One entry is approved, not the whole day: only that entry is paid.

        Guards job.api.approve_cost_line and workshop_timesheet_service._week_hours.
        """
        first = _book(worker, worker, job, at(7), at(8))
        _book(worker, worker, job, at(9), at(10))

        response = authenticated_client(office_staff).post(
            APPROVE_LINE_URL.format(line_id=first["id"])
        )

        assert response.status_code == 200, response.content
        assert _week(worker) == {"approved_hours": 1.0, "waiting_hours": 1.0}

    def test_s3_a_break_added_over_a_whole_entry_leaves_it_for_the_office_to_judge(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """He adds a break exactly over his 10:00-10:15 entry: two stories for one quarter hour.

        Nothing is refused and nothing changes the entry (owner, 2026-10-25):
        both wait, the office sees both, and approving pays both as entered.

        Guards attendance.add_break and approval.approve_day.
        """
        attendance.set_clock_times(worker, DAY, at(7), at(15), worker)
        entry = _book(worker, worker, job, at(10), at(10, 15))
        attendance.add_break(worker, DAY, at(10), at(10, 15), paid=True, actor=worker)

        shown = [each for each in _row(worker)["entries"] if each["id"] == entry["id"]]
        assert [(each["hours"], each["approved"]) for each in shown] == [(0.25, False)]

        approval.approve_day(worker, DAY, office_staff)

        line = _line(entry)
        # 0.25h at the worker's 48.00 = 12.00, as he entered it.
        assert (line.approved, line.total_cost) == (True, Decimal("12.00"))

    def test_s4_a_day_with_overtime_left_on_a_short_day_is_approved_as_it_is(
        self, office_staff: Staff, worker: Staff, job: Job, company: Company, superuser: Staff
    ) -> None:
        """A day carrying the overtime flag (E10) is approved anyway: approved as is.

        5h on X, 4h on Y (its last hour at 1.5x), then X deleted. The flag
        does not block, and Y's overtime hour stays at 1.5x.

        Guards approval.approve_day.
        """
        job_y = make_job(company, superuser, name="Job Y")
        x = _untimed(worker, worker, job, "5")
        _untimed(worker, worker, job_y, "4")
        workshop_timesheet_service.delete_entry(worker, UUID(x["id"]))

        assert approval.approve_day(worker, DAY, office_staff) == 2

        # Y crossed 8h at 5 + 3: 3h ordinary, then 1h at time and a half.
        assert _hours_by_rate(job_y, worker) == {1.0: Decimal("3.000"), 1.5: Decimal("1.000")}
        assert all(line.approved for line in _lines(job_y, worker))


class TestClocksDatesAndRounding:
    pytestmark = DATABASE

    def test_l1_a_night_job_past_midnight_is_kept_as_hours_without_times(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """A night job from 22:00 to 02:00.

        It can't be stored across midnight. The office sets 23:59 and the
        hours stand (4h), with no times past midnight.

        Guards workshop_timesheet_service._validate_time_consistency and _redraw_finish.
        """
        across_midnight: WorkshopEntryCreateData = {
            "job_id": job.id,
            "accounting_date": DAY,
            "hours": Decimal("4"),
            "start_time": at(22),
            "end_time": at(2),
        }
        with pytest.raises(ValueError, match=exactly(BACKWARDS_REFUSAL)):
            workshop_timesheet_service.create_entry(office_staff, worker, across_midnight)

        entry = _book(office_staff, worker, job, at(22), at(23, 59))
        corrected = workshop_timesheet_service.update_entry(
            office_staff, {"entry_id": UUID(entry["id"]), "hours": Decimal("4")}
        )

        assert (corrected["hours"], corrected["start_time"], corrected["end_time"]) == (
            4.0,
            None,
            None,
        )

    def test_l2_on_the_daylight_saving_days_an_entry_is_the_hours_he_was_there(
        self, worker_client: Client
    ) -> None:
        """An entry 01:00-04:00 on each NZ daylight-saving day (Proposed).

        Clocks go 02:00 to 03:00 in September and 03:00 to 02:00 in April: 2h
        in September and 4h in April, the hours he was actually there. A
        wall-clock subtraction says 3h on both.

        Guards attendance.hours_for (the placement the drawer saves).
        """
        nz = ZoneInfo("Pacific/Auckland")
        spring_forward, fall_back = date(2026, 9, 27), date(2026, 4, 5)

        def elapsed(day: date) -> timedelta:
            start = datetime.combine(day, at(1), nz).astimezone(UTC)
            return datetime.combine(day, at(4), nz).astimezone(UTC) - start

        # The 2026 transitions, from the zone database rather than memory.
        assert elapsed(spring_forward) == timedelta(hours=2)
        assert elapsed(fall_back) == timedelta(hours=4)
        assert elapsed(spring_forward - timedelta(days=7)) == timedelta(hours=3)

        def placed_hours(day: date) -> float:
            response = worker_client.get(
                PLACEMENT_URL, {"date": day.isoformat(), "start": "01:00", "finish": "04:00"}
            )
            assert response.status_code == 200, response.content
            hours: float = response.json()["hours"]
            return hours

        assert placed_hours(spring_forward) == 2.0
        assert placed_hours(fall_back) == 4.0

    def test_l3_today_is_the_nz_date_at_half_past_eleven_at_night(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job
    ) -> None:
        """An entry saved at 23:30 NZ time for "today": the date is the NZ date, not UTC's.

        Guards workshop_timesheet_service.resolve_entry_date and entered_late.
        """
        # 23:30 NZST on Monday 4 May is 11:30 UTC the same day.
        monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 5, 4, 11, 30, tzinfo=UTC))
        today = workshop_timesheet_service.resolve_entry_date(None)
        entry = _untimed(worker, worker, job, "1", day=today)

        assert today == date(2026, 5, 4)
        assert (entry["accounting_date"], entry["entered_late"]) == (date(2026, 5, 4), False)

        # 00:30 NZST on Tuesday 5 May is still Monday 12:30 in UTC.
        monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 5, 4, 12, 30, tzinfo=UTC))
        assert workshop_timesheet_service.resolve_entry_date(None) == date(2026, 5, 5)

    def test_l4_a_sunday_entry_belongs_to_the_week_it_falls_in(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """An entry on the Sunday before a Monday-start pay week belongs to the week it falls in.

        Guards weekly_timesheet_service.payroll_week_start and
        workshop_timesheet_service._week_hours.
        """
        _untimed(office_staff, worker, job, "3", day=SUNDAY_BEFORE)

        assert payroll_week_start(SUNDAY_BEFORE) == date(2026, 4, 27)
        assert _week(worker, SUNDAY_BEFORE) == {"approved_hours": 0.0, "waiting_hours": 3.0}
        assert _week(worker, DAY) == {"approved_hours": 0.0, "waiting_hours": 0.0}

    @pytest.mark.usefixtures("general_work")
    def test_l6_the_sweep_rounds_to_quarters_but_never_into_his_entry(
        self, office_staff: Staff, worker: Staff, job: Job, general_work: Job
    ) -> None:
        """Clocked in at 06:58, entry from 07:07.

        The sweep's windows round to quarter hours but never into the entry:
        06:58-07:00 is not invented as 07:00-07:15.

        Guards attendance.unallocated_windows.
        """
        attendance.set_clock_times(worker, DAY, at(6, 58), at(9), worker)
        _book(worker, worker, job, at(7, 7), at(8))

        approval.sweep_person(worker, [DAY], office_staff)

        # 06:58 rounds to 07:00, which the 07:07 entry leaves no quarter of;
        # then 08:00 to the 08:30 break, and 08:45 to the 09:00 clock-out.
        assert _swept(general_work, worker) == [
            ("08:00:00", "08:30:00", Decimal("0.500")),
            ("08:45:00", "09:00:00", Decimal("0.250")),
        ]

    def test_l8_a_stop_before_the_start_is_refused(self, worker: Staff, job: Job) -> None:
        """An entry with its stop before its start (13:00-12:00).

        Refused: "The finish time must be after the start time."

        Guards workshop_timesheet_service._validate_time_consistency.
        """
        backwards: WorkshopEntryCreateData = {
            "job_id": job.id,
            "accounting_date": DAY,
            "hours": Decimal("1"),
            "start_time": at(13),
            "end_time": at(12),
        }

        with pytest.raises(ValueError, match=exactly(BACKWARDS_REFUSAL)):
            workshop_timesheet_service.create_entry(worker, worker, backwards)

        assert _lines(job, worker) == []

    def test_l9_an_entry_from_midnight_to_midnight_is_refused(
        self, worker: Staff, job: Job
    ) -> None:
        """An entry 00:00-00:00: refused.

        Guards workshop_timesheet_service._validate_time_consistency.
        """
        no_span: WorkshopEntryCreateData = {
            "job_id": job.id,
            "accounting_date": DAY,
            "hours": Decimal("1"),
            "start_time": at(0),
            "end_time": at(0),
        }

        with pytest.raises(ValueError, match=exactly(BACKWARDS_REFUSAL)):
            workshop_timesheet_service.create_entry(worker, worker, no_span)

        assert _lines(job, worker) == []


def _approve_on_screen(client: Client, worker: Staff) -> int:
    """Approve his day as the Approve time screen does: the endpoint, in its transaction."""
    response = client.post(APPROVE_DAY_URL.format(staff_id=worker.id, day=DAY.isoformat()))
    assert response.status_code == 200, response.content
    approved: int = response.json()["approved_count"]
    return approved


def _race(first: Callable[[], object], second: Callable[[], object]) -> None:
    """Run ``first`` in a transaction and ``second`` on another connection behind its lock.

    ``await_database_lock`` proves the second genuinely waited on the first:
    the two writes overlap, and the order they commit in is the one named.
    The second's exception, if any, is raised here.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            first()
            pending, worker_pid = start_database_task(pool, second)
            await_database_lock(pending, worker_pid)
        pending.result(timeout=10)


class TestTwoThingsAtOnce:
    """Real concurrent transactions: each second write is shown to wait on the first's lock.

    ``committed_db``, not ``django_db(transaction=True)``: this project
    refuses Django's flush (ADR 0048), and the disposable committed database
    is how its other contention tests race real commits.
    """

    pytestmark = COMMITTED

    @pytest.mark.usefixtures("general_work")
    @pytest.mark.parametrize("first", ["his_save", "the_sweep"])
    def test_m1_his_save_and_the_offices_sweep_never_pay_the_time_twice(
        self, office_staff: Staff, worker: Staff, job: Job, first: str
    ) -> None:
        """He saves an entry while the office sweeps his day.

        The sweep reads his entries after his save, or he waits for it. The
        time is never paid twice.

        Guards approval._sweep and workshop_timesheet_service.create_entry (his lock).
        """
        attendance.set_clock_times(worker, DAY, at(7), at(15), worker)

        def save() -> None:
            _book(worker, worker, job, at(9), at(11))

        def sweep() -> None:
            approval.sweep_person(worker, [DAY], office_staff)

        if first == "his_save":
            _race(save, sweep)
            # The sweep saw X: General work 5h + X 2h + paid breaks 0.5h.
            assert _week(worker) == {"approved_hours": 7.5, "waiting_hours": 0.0}
        else:
            _race(sweep, save)
            # The paid breaks are approved; X's 2h and the General work round
            # it (5h), changed after the sweep, wait for the office.
            assert _week(worker) == {"approved_hours": 0.5, "waiting_hours": 7.0}

    def test_m2_two_phones_saving_past_the_usual_day_count_the_overtime_once(
        self, worker: Staff, job: Job
    ) -> None:
        """He saves two entries from two phones at once, each taking the day past 8h.

        His lock puts them one after the other. The second sees the first, so
        the overtime is counted once.

        Guards workshop_timesheet_service.create_entry and overtime_hours.
        """
        _untimed(worker, worker, job, "6")

        _race(
            lambda: _untimed(worker, worker, job, "3"),
            lambda: _untimed(worker, worker, job, "3"),
        )

        # 6 + 3 + 3 = 12h: the first 8 ordinary, the 4 past them at time and a half.
        assert _hours_by_rate(job, worker) == {1.0: Decimal("8.000"), 1.5: Decimal("4.000")}

    def test_m3_two_office_staff_approving_one_day_approve_each_entry_once(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """Two office staff approve the same day at once.

        Both succeed, each entry is approved once, and no error.

        Guards approval.approve_day.
        """
        second_office = make_staff(
            "timesheet-office-two@example.com",
            is_office_staff=True,
            xero_user_id="",
            first_name="Oscar",
            last_name="Office",
        )
        _book(worker, worker, job, at(7), at(8))
        _book(worker, worker, job, at(9), at(10))
        first_office = authenticated_client(office_staff)
        other_office = authenticated_client(second_office)
        counts: list[int] = []

        _race(
            lambda: counts.append(_approve_on_screen(first_office, worker)),
            lambda: counts.append(_approve_on_screen(other_office, worker)),
        )

        assert counts == [2, 0]
        approvals = Counter(
            TimesheetEvent.objects.filter(event_type="entry_approved").values_list(
                "cost_line_id", flat=True
            )
        )
        assert sorted(approvals.values()) == [1, 1]
        assert all(line.approved for line in _lines(job, worker))

    @pytest.mark.parametrize("first", ["the_approval", "his_save"])
    def test_m5_his_stale_save_against_the_offices_edit_and_approval(
        self, office_staff: Staff, worker: Staff, job: Job, first: str
    ) -> None:
        """The office edits his entry while he has it open; he then saves his stale copy.

        The last save wins and both are audited. His save after the approval
        is his change to approved time, so it waits for the office again.

        Guards workshop_timesheet_service.update_entry and approval.approve_day.
        """
        entry = _book(worker, worker, job, at(9), at(11))
        entry_id = UUID(entry["id"])
        # The office corrects 2h to 1.5h: still waiting, correcting is not approving.
        workshop_timesheet_service.update_entry(
            office_staff, {"entry_id": entry_id, "hours": Decimal("1.5")}
        )

        office = authenticated_client(office_staff)

        def approve() -> None:
            _approve_on_screen(office, worker)

        def stale_save() -> None:
            workshop_timesheet_service.update_entry(
                worker, {"entry_id": entry_id, "hours": Decimal("2"), "end_time": at(11)}
            )

        if first == "the_approval":
            _race(approve, stale_save)
            approved = False
        else:
            _race(stale_save, approve)
            approved = True

        line = CostLine.objects.get(id=entry_id)
        assert (line.quantity, line.approved) == (Decimal("2.000"), approved)
        editors = [office_staff.id, worker.id]
        updates = TimesheetEvent.objects.filter(
            cost_line_id=entry_id, event_type="entry_updated"
        ).order_by("timestamp")
        assert [event.staff_id for event in updates] == editors

    @pytest.mark.usefixtures("general_work")
    @pytest.mark.parametrize("first", ["his_clock_out", "the_sweep"])
    def test_m6_a_clock_out_during_a_sweep_is_seen_whole_or_not_at_all(
        self, office_staff: Staff, worker: Staff, general_work: Job, first: str
    ) -> None:
        """He clocks out while the office sweeps.

        The sweep either sees him still clocked in (skips him) or sees the
        finish. Never half of each.

        Guards approval._sweep and attendance.clock_out.
        """
        today = timezone.localdate()
        local = timezone.get_current_timezone()
        attendance.clock_in(worker, datetime.combine(today, at(7), local))
        results: list[approval.SweepData] = []

        def clock_out() -> None:
            # At noon: the untouched 13:30 break is taken off, under his lock.
            attendance.clock_out(worker, datetime.combine(today, at(12), local))

        def sweep() -> None:
            results.append(approval.sweep_person(worker, [today], office_staff))

        if first == "his_clock_out":
            _race(clock_out, sweep)
            [result] = results
            # 07:00-08:30 and 08:45-11:30, up to lunch: 1.5h + 2.75h.
            assert result["skipped"] == []
            assert _swept(general_work, worker) == [
                ("07:00:00", "08:30:00", Decimal("1.500")),
                ("08:45:00", "11:30:00", Decimal("2.750")),
            ]
        else:
            _race(sweep, clock_out)
            [result] = results
            assert [skip["reason"] for skip in result["skipped"]] == ["still_clocked_in"]
            assert _swept(general_work, worker) == []
        assert AttendanceDay.objects.get(staff=worker, date=today).clock_out == at(12)


@pytest.mark.usefixtures("general_work")
class TestStaffChanges:
    pytestmark = DATABASE

    def test_n1_a_new_starter_is_not_booked_before_his_start_date(
        self, office_staff: Staff
    ) -> None:
        """A new starter, employed from Wednesday; the office sweeps the whole week (Proposed).

        No standard day is assumed before his start date, so Monday and
        Tuesday aren't booked, from the everyone sweep or from his own row.

        Guards approval._sweep and approval._assumed_standard.
        """
        starter = make_staff("timesheet-starter@example.com", first_name="Nat", last_name="New")
        starter.employment_start_date = WEDNESDAY
        starter.save(update_fields=["employment_start_date"])
        week = [DAY + timedelta(days=offset) for offset in range(5)]

        approval.sweep_everyone(week, office_staff)
        approval.sweep_person(starter, week, office_staff)

        booked = set(
            CostLine.objects.filter(staff=starter, kind="time").values_list(
                "accounting_date", flat=True
            )
        )
        assert booked == {WEDNESDAY, THURSDAY, FRIDAY}
        assert not AttendanceDay.objects.filter(staff=starter, date__lt=WEDNESDAY).exists()

    def test_n2_a_leaver_is_not_booked_after_his_last_day_and_time_after_it_is_refused(
        self, office_staff: Staff, job: Job
    ) -> None:
        """A leaver, finishing Thursday; the office sweeps Friday (Proposed).

        No standard day is assumed after his finish date, and entries after it
        are refused.

        Guards approval._assumed_standard and workshop_timesheet_service.create_entry.
        """
        leaver = make_staff("timesheet-leaver@example.com", first_name="Lee", last_name="Leaver")
        # Employment ends strictly before date_left: Thursday is his last day.
        leaver.date_left = FRIDAY
        leaver.save(update_fields=["date_left"])

        approval.sweep_everyone([FRIDAY], office_staff)
        approval.sweep_person(leaver, [FRIDAY], office_staff)

        assert not CostLine.objects.filter(staff=leaver, accounting_date=FRIDAY).exists()
        # Opus: the refusal's wording is a proposal for the owner to confirm.
        with pytest.raises(
            InvalidInputError,
            match=exactly(
                "Lee Leaver's last day was 2026-05-07, so time after it can't be entered."
            ),
        ):
            _untimed(office_staff, leaver, job, "2", day=FRIDAY)

    def test_n3_a_wage_change_leaves_earlier_entries_at_the_old_wage_until_repriced(
        self, worker: Staff, job: Job
    ) -> None:
        """His wage changes on Wednesday.

        Entries before then keep the old wage. An edit to a Monday entry after
        the change reprices only if its billing or rate changes.

        Guards workshop_timesheet_service.update_entry (reprice only on billing).
        """
        entry = _book(worker, worker, job, at(9), at(11))
        entry_id = UUID(entry["id"])
        worker.base_wage_rate = Decimal("50.00")
        worker.save()

        workshop_timesheet_service.update_entry(
            worker, {"entry_id": entry_id, "hours": Decimal("1.5")}
        )
        # The old wage: 40.00 + 20% = 48.00.
        assert _line(entry).unit_cost == Decimal("48.00")

        workshop_timesheet_service.update_entry(
            worker, {"entry_id": entry_id, "is_billable": False}
        )
        # Repriced at the new wage: 50.00 + 20% = 60.00.
        assert _line(entry).unit_cost == Decimal("60.00")

    def test_n5_time_the_office_enters_waits_until_it_is_approved_theirs_included(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """Entering and approving are two operations, even by one person (owner, 2026-10-26).

        Office staff approve their own time ("of course office staff approve
        their own time"), as a step of its own.

        Guards workshop_timesheet_service._save_entry (approved=).
        """
        own = _book(office_staff, office_staff, job, at(9), at(11))
        for_worker = _book(office_staff, worker, job, at(9), at(11))

        assert (_line(own).approved, _line(for_worker).approved) == (False, False)
        assert approval.approve_day(office_staff, DAY, office_staff) == 1
        assert approval.approve_day(worker, DAY, office_staff) == 1
        assert (_line(own).approved, _line(for_worker).approved) == (True, True)

    def test_n5_a_grid_time_row_the_office_enters_waits_and_its_material_does_not(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """The office entry grid is entering too; material approval is a stock matter.

        Guards job_service.create_cost_line (approved=).
        """
        data: CostLineWriteData = {
            "kind": "time",
            "desc": None,
            "quantity": Decimal("2"),
            "accounting_date": DAY,
            "ext_refs": {},
            "meta": {
                "created_from_timesheet": True,
                "staff_id": str(worker.id),
                "date": DAY.isoformat(),
                "is_billable": True,
                "wage_rate_multiplier": 1.0,
            },
        }
        line = create_cost_line(job, "actual", data, office_staff)

        assert line.approved is False

    def test_n5_the_breaks_the_office_puts_on_with_clock_times_wait_too(
        self, office_staff: Staff, worker: Staff
    ) -> None:
        """Setting his clock times is entering; the breaks it puts on wait for approval.

        Guards attendance.set_clock_times (the standard breaks it records).
        """
        attendance.set_clock_times(worker, DAY, at(7), at(15), office_staff)

        breaks = workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        assert [each["approved"] for each in breaks] == [False, False, False]

    def test_n7_a_new_default_labour_type_leaves_existing_entries_theirs(
        self, worker: Staff, job: Job
    ) -> None:
        """His default labour type changes: existing entries keep theirs.

        Guards workshop_timesheet_service.update_entry (labour_subtype=line's own).
        """
        workshop = LabourSubtype.default_workshop()
        office = LabourSubtype.default_non_workshop()
        before = _book(worker, worker, job, at(9), at(10))
        worker.default_labour_subtype = office
        worker.save(update_fields=["default_labour_subtype"])

        # A rate change reprices the entry; its labour type must stand.
        workshop_timesheet_service.update_entry(
            worker, {"entry_id": UUID(before["id"]), "wage_rate_multiplier": Decimal("1.5")}
        )
        after = _book(worker, worker, job, at(10), at(11))

        assert _line(before).labour_subtype_id == workshop.id
        assert _line(after).labour_subtype_id == office.id


class TestJobsChangingUnderTheTime:
    pytestmark = DATABASE

    def test_o1_waiting_time_on_an_archived_job_is_approved_and_paid(
        self, office_staff: Staff, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        """The job is archived with entries still waiting.

        The entries stay, are approvable, and are paid. No new entries go on
        it: the job picker no longer offers it.

        Guards approval.approve_day and timesheet_entry_options.get_jobs_for_entry.
        """
        entry = _book(worker, worker, job, at(9), at(11))
        job.status = "archived"
        job.save(staff=superuser)

        assert approval.approve_day(worker, DAY, office_staff) == 1

        assert _line(entry).approved is True
        assert _week(worker) == {"approved_hours": 2.0, "waiting_hours": 0.0}
        offered = {each["id"] for each in get_jobs_for_entry(worker)["jobs"]}
        assert job.id not in offered

    def test_o2_existing_entries_keep_the_charge_out_rate_they_were_priced_at(
        self, worker: Staff, job: Job
    ) -> None:
        """The job's charge-out rate changes after entries exist.

        Existing entries keep the rate they were priced at.

        Guards workshop_timesheet_service.update_entry (no reprice on hours).
        """
        entry = _book(worker, worker, job, at(9), at(11))
        job.labour_rates.filter(labour_subtype=LabourSubtype.default_workshop()).update(
            charge_out_rate=Decimal("150.00")
        )

        workshop_timesheet_service.update_entry(
            worker, {"entry_id": UUID(entry["id"]), "hours": Decimal("1.5")}
        )
        later = _book(worker, worker, job, at(13, 45), at(15))

        assert _line(entry).unit_rev == Decimal("120.00")
        assert _line(later).unit_rev == Decimal("150.00")

    def test_o4_moving_to_a_shop_job_makes_it_unbillable_and_back_billable(
        self, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        """An entry moved from a customer job to a shop job, and back.

        It becomes unbillable; moved back, it's billable again.

        Guards job_service.move_time_line.
        """
        shop = make_job(CompanyDefaults.get_solo().shop_company, superuser, name="Workshop tidy")
        entry = _book(worker, worker, job, at(9), at(11))
        entry_id = UUID(entry["id"])

        moved = workshop_timesheet_service.update_entry(
            worker, {"entry_id": entry_id, "job_id": shop.id}
        )
        assert (moved["is_billable"], _line(entry).unit_rev) == (False, Decimal("0.00"))

        back = workshop_timesheet_service.update_entry(
            worker, {"entry_id": entry_id, "job_id": job.id}
        )
        # 2h at 120.00 = 240.00.
        assert (back["is_billable"], _line(entry).total_rev) == (True, Decimal("240.00"))

    def test_o6_on_a_fixed_price_job_the_hours_never_change_the_bill(
        self, superuser: Staff, worker: Staff, company: Company
    ) -> None:
        """A fixed-price job: time is cost only, so the bill doesn't change with hours.

        Guards invoice_calculation.get_job_invoicing_basis.
        """
        fixed = make_job(company, superuser, name="Gate", pricing_methodology="fixed_price")
        fixed.labour_rates.filter(labour_subtype=LabourSubtype.default_workshop()).update(
            charge_out_rate=Decimal("120.00")
        )
        # The accepted quote, made on the quoting screens: 1000.00.
        make_material_line(fixed, set_kind="quote", rev="1000.00", cost="400.00")

        _book(worker, worker, fixed, at(9), at(11))
        first = get_job_invoicing_basis(Job.objects.get(pk=fixed.pk)).target_total
        _book(worker, worker, fixed, at(13, 45), at(15))

        assert first == Decimal("1000.00")
        assert get_job_invoicing_basis(Job.objects.get(pk=fixed.pk)).target_total == (
            Decimal("1000.00")
        )
        # The cost follows the hours: (2h + 1.25h) x 48.00 = 156.00.
        assert _summary(fixed)["cost"] == 156.0

    def test_o7_the_break_job_is_never_billable_even_when_asked(
        self, worker: Staff, break_job: Job
    ) -> None:
        """The Break job is never billable, even if a request says it is.

        Guards CostLine._save_validated (shop jobs bill nobody).
        """
        billable_break: WorkshopEntryCreateData = {
            "job_id": break_job.id,
            "accounting_date": DAY,
            "hours": Decimal("0.25"),
            "start_time": at(10),
            "end_time": at(10, 15),
            "is_billable": True,
        }

        with pytest.raises(
            ValidationError,
            match=re.escape(
                "Shop job time entries cannot be billable. "
                f"Job 'Break' (job_number={break_job.job_number})"
            ),
        ):
            workshop_timesheet_service.create_entry(worker, worker, billable_break)

        assert _lines(break_job, worker) == []


class TestPayrollAndBilling:
    pytestmark = DATABASE

    def test_j4_time_on_a_shop_job_is_never_billed(self, superuser: Staff, worker: Staff) -> None:
        """A shop job's time is never billed (the fill-day sheet's row on one).

        Guards day_submission.submit_day (is_billable=bills_its_time).
        """
        shop = make_job(CompanyDefaults.get_solo().shop_company, superuser, name="Workshop tidy")
        attendance.set_clock_times(worker, DAY, at(7), at(15), worker)

        day_submission.submit_day(
            worker,
            DAY,
            [
                {
                    "job_id": shop.id,
                    "hours": Decimal("2"),
                    "description": None,
                    "time_and_a_half": False,
                }
            ],
            None,
            timezone.now(),
        )

        [line] = _lines(shop, worker)
        assert (line.quantity, line.meta["is_billable"], line.total_rev) == (
            Decimal("2.000"),
            False,
            Decimal("0"),
        )
        # Costed, never charged: 2h x 48.00.
        assert _summary(shop) == {"cost": 96.0, "rev": 0.0, "hours": 2.0}

    def test_j5_waiting_time_is_on_the_jobs_costs_and_bill_before_approval(
        self, worker: Staff, job: Job
    ) -> None:
        """Billing never waits for approval (owner, 2026-10-25).

        Worked 09:00-11:00, collected and paid for at 13:00, the timesheet
        approved at 16:00. His waiting 2h is on the job's actual costs and the
        invoice from the moment he saves it. Approval gates pay only.

        Guards workshop_timesheet_service._save_entry and
        invoice_calculation.get_job_invoicing_basis.
        """
        entry = _book(worker, worker, job, at(9), at(11))

        assert _line(entry).approved is False
        # 2h x 48.00 = 96.00 cost; 2h x 120.00 = 240.00 revenue.
        assert _summary(job) == {"cost": 96.0, "rev": 240.0, "hours": 2.0}
        assert get_job_invoicing_basis(Job.objects.get(pk=job.pk)).target_total == (
            Decimal("240.00")
        )
        assert _week(worker) == {"approved_hours": 0.0, "waiting_hours": 2.0}

    def test_j6_correcting_the_entry_on_approval_moves_the_costs_not_the_issued_invoice(
        self, office_staff: Staff, worker: Staff, job: Job, company: Company
    ) -> None:
        """The office corrects that entry down to 1.5h when approving, after the invoice went out.

        Job costs show 1.5h. The issued invoice is not changed by the timesheet.

        Guards workshop_timesheet_service.update_entry.
        """
        entry = _book(worker, worker, job, at(9), at(11))
        # The invoice issued at 13:00 for the 2h, made through Xero: 240.00.
        invoice = make_invoice(
            company, job=job, status="AUTHORISED", total_excl_tax=Decimal("240.00")
        )

        workshop_timesheet_service.update_entry(
            office_staff, {"entry_id": UUID(entry["id"]), "hours": Decimal("1.5")}
        )
        approval.approve_day(worker, DAY, office_staff)

        # 1.5h x 48.00 = 72.00; 1.5h x 120.00 = 180.00.
        assert _summary(job) == {"cost": 72.0, "rev": 180.0, "hours": 1.5}
        invoice.refresh_from_db()
        assert invoice.total_excl_tax == Decimal("240.00")


class TestBilling:
    pytestmark = DATABASE

    def test_u1_deleting_invoiced_waiting_time_drops_job_costs_not_the_draft_invoice(
        self, worker: Staff, job: Job, company: Company
    ) -> None:
        """An invoice is drafted from job costs including his waiting time; he deletes the entry.

        The draft invoice isn't changed by the timesheet, and job costs drop.

        Guards workshop_timesheet_service.delete_entry.
        """
        entry = _book(worker, worker, job, at(9), at(11))
        # Drafted in Xero from the 2h: 240.00.
        draft = make_invoice(company, job=job, status="DRAFT", total_excl_tax=Decimal("240.00"))

        workshop_timesheet_service.delete_entry(worker, UUID(entry["id"]))

        assert _summary(job) == {"cost": 0.0, "rev": 0.0, "hours": 0.0}
        draft.refresh_from_db()
        assert draft.total_excl_tax == Decimal("240.00")

    def test_u2_an_entry_he_marked_non_billable_stays_so_when_approved(
        self, office_staff: Staff, worker: Staff, job: Job
    ) -> None:
        """A non-billable entry he marked, which the office approves.

        It stays non-billable unless the office changes it.

        Guards approval.approve_line.
        """
        entry = _book(worker, worker, job, at(9), at(11), is_billable=False)

        approval.approve_day(worker, DAY, office_staff)

        line = _line(entry)
        assert (line.approved, line.meta["is_billable"], line.total_rev) == (
            True,
            False,
            Decimal("0"),
        )


class TestEnteringIt:
    pytestmark = DATABASE

    @pytest.mark.usefixtures("company_address")
    def test_w1_an_entry_sent_the_next_morning_is_late_and_remote_never_refused(
        self, worker: Staff, job: Job
    ) -> None:
        """An offline phone sends an entry the next morning.

        Flagged late, no location (so remote), never refused.

        Guards workshop_timesheet_service.entered_late and location.saved_remotely.
        """
        yesterday = timezone.localdate() - timedelta(days=1)

        entry = _untimed(worker, worker, job, "2", day=yesterday)

        assert (entry["hours"], entry["entered_late"], entry["remote_entry"]) == (2.0, True, True)

    def test_w2_the_same_times_on_two_jobs_are_two_lines_the_office_sees(
        self, superuser: Staff, worker: Staff, job: Job, company: Company
    ) -> None:
        """The same entry saved twice (two jobs, same times).

        Two lines. The office sees the overlap.

        Guards workshop_timesheet_service.create_entry and approval._staff_day.
        """
        other = make_job(company, superuser, name="Second job")
        _book(worker, worker, job, at(9), at(10))
        _book(worker, worker, other, at(9), at(10))

        shown = sorted(
            (each["job_name"], each["start_time"], each["end_time"], each["hours"])
            for each in _row(worker)["entries"]
        )
        assert shown == [
            ("Second job", at(9), at(10), 1.0),
            ("Timesheet Job", at(9), at(10), 1.0),
        ]

    def test_w3_a_fill_sheet_row_off_the_quarter_hour_is_refused(
        self, worker: Staff, job: Job
    ) -> None:
        """The fill-day sheet with a row that isn't a quarter hour (1.1h).

        Refused: "Hours are entered in quarter hours, a quarter or more." The
        day stays as it was, unsent.

        Guards day_submission.lay_out_rows.
        """
        attendance.set_clock_times(worker, DAY, at(7), at(15), worker)

        with pytest.raises(
            InvalidInputError,
            match=exactly("Hours are entered in quarter hours, a quarter or more."),
        ):
            day_submission.submit_day(
                worker,
                DAY,
                [
                    {
                        "job_id": job.id,
                        "hours": Decimal("1.1"),
                        "description": None,
                        "time_and_a_half": False,
                    }
                ],
                None,
                timezone.now(),
            )

        assert _lines(job, worker) == []
        assert AttendanceDay.objects.get(staff=worker, date=DAY).submitted_at is None

    def test_w4_a_finish_typed_inside_a_break_takes_only_the_break_inside_the_span(
        self, worker: Staff, worker_client: Client
    ) -> None:
        """The drawer with a typed finish inside a break.

        The hours are the span less the part of the break inside it.

        Guards attendance.hours_for (the drawer's placement).
        """
        attendance.set_clock_times(worker, DAY, at(7), at(15), worker)

        response = worker_client.get(
            PLACEMENT_URL, {"date": DAY.isoformat(), "start": "08:00", "finish": "08:40"}
        )

        assert response.status_code == 200, response.content
        # 08:00-08:40 is 40 minutes, 10 of them inside the 08:30-08:45 break: 0.5h.
        assert response.json()["hours"] == 0.5
