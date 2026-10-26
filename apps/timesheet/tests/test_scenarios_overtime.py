# ruff: noqa: N802 -- tests are named by the plan's scenario ids (E1, P9, N4)
"""Overtime, urgent jobs and the hairy overtime cases (plan sections E, F, P; N4, O3, O5, U3).

Each test is one scenario from the owner's list, set up through the services
the screens call. Company defaults in tests: the usual day is 07:00-15:00
Monday to Friday (8h), breaks 08:30-08:45 paid, 11:30-12:00 unpaid lunch,
13:30-13:45 paid. The worker's wage is 48.00 (40 base + 20% loading); the
job's charge-out rate is 120.00. Every expected number is worked by hand in
the comment beside it, never by calling the code under test.
"""

from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.job.services.job_service import CostLineWriteData, create_cost_line
from apps.timesheet.models import LeaveType
from apps.timesheet.services import (
    approval,
    attendance,
    day_submission,
    leave_service,
    workshop_timesheet_service,
)
from apps.timesheet.services.workshop_timesheet_service import WorkshopEntryCreateData
from apps.timesheet.tests.conftest import (
    WEEK_START,
    make_leave_job,
    make_public_holiday_job,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]

DAY = WEEK_START  # Monday 2026-05-04
FRIDAY = WEEK_START + timedelta(days=4)
SATURDAY = WEEK_START + timedelta(days=5)
PLACEMENT_URL = "/api/timesheets/my-day/placement/"
DEFAULTS_URL = "/api/company-defaults/"

#: One line as the office reads it: "start-stop" (or "untimed"), hours, pay rate,
#: charge rate, unit cost, unit revenue, approved.
Line = tuple[str, str, float, float, str, str, bool]


def T(value: str) -> time:
    return time.fromisoformat(value)


def _span(line: CostLine) -> str:
    """Start and stop as hh:mm-hh:mm; "untimed" for an entry with no picture (past midnight)."""
    # Absent when saved without times; None after an edit cleared them.
    start, end = line.meta.get("start_time"), line.meta.get("end_time")
    if start is None or end is None:
        return "untimed"
    return f"{str(start)[:5]}-{str(end)[:5]}"


def _lines(job: Job, staff: Staff) -> list[Line]:
    """The job's time lines for him, in the order they were made."""
    return [
        (
            _span(line),
            str(line.quantity),
            float(str(line.meta["wage_rate_multiplier"])),
            float(str(line.meta["bill_rate_multiplier"])),
            str(line.unit_cost),
            str(line.unit_rev),
            line.approved,
        )
        for line in CostLine.objects.filter(
            staff=staff, cost_set__job=job, cost_set__kind="actual", kind="time"
        ).order_by("created_at")
    ]


def _line_ids(job: Job, staff: Staff) -> list[CostLine]:
    return list(
        CostLine.objects.filter(staff=staff, cost_set__job=job, kind="time").order_by("created_at")
    )


def _drawer(  # noqa: PLR0913 -- the drawer's fields, each one a scenario's axis
    worker: Staff,
    job: Job,
    hours: str,
    start: str | None = None,
    end: str | None = None,
    *,
    rate: str = "1.0",
    billable: bool = True,
    day: date = DAY,
    bill: str | None = None,
) -> None:
    """Save an entry as the My time drawer sends it: hours, times if any, rate, billable."""
    data: WorkshopEntryCreateData = {
        "job_id": job.id,
        "accounting_date": day,
        "hours": Decimal(hours),
        "start_time": None if start is None else T(start),
        "end_time": None if end is None else T(end),
        "description": None,
        "is_billable": billable,
        "wage_rate_multiplier": Decimal(rate),
    }
    if bill is not None:
        data["bill_rate_multiplier"] = Decimal(bill)
    workshop_timesheet_service.create_entry(worker, worker, data)


def _clock(worker: Staff, start: str, finish: str, day: date = DAY) -> None:
    """His clock times, set as the My time screen sets them; puts his standard breaks on."""
    attendance.set_clock_times(worker, day, T(start), T(finish), worker)


def _grid(office: Staff, job: Job, worker: Staff, hours: str, *, bill: float) -> None:
    """An office entry-grid row as SmartTimesheetTable posts it (wage 1.0, bill from the pick)."""
    data: CostLineWriteData = {
        "kind": "time",
        "desc": None,
        "quantity": Decimal(hours),
        "accounting_date": DAY,
        "meta": {
            "staff_id": str(worker.id),
            "date": DAY.isoformat(),
            "is_billable": True,
            "wage_rate_multiplier": 1.0,
            "bill_rate_multiplier": bill,
            "created_from_timesheet": True,
        },
    }
    create_cost_line(job, "actual", data, office)


def _job(company: Company, superuser: Staff, name: str, rate: str = "120.00") -> Job:
    other = make_job(company, superuser, name=name)
    other.labour_rates.filter(labour_subtype=LabourSubtype.default_workshop()).update(
        charge_out_rate=Decimal(rate)
    )
    return other


def _make_urgent(job: Job, superuser: Staff) -> None:
    """The job screen's urgent switch, saved on the job."""
    job.is_urgent = True
    job.save(staff=superuser, update_fields=["is_urgent", "updated_at"])


def _approval_row(day: date, worker: Staff) -> dict[str, object]:
    """His row on Approve time, as a plain dict so a key the screen lacks is a KeyError."""
    rows = [
        dict(row)
        for row in approval.day_approvals(day)["staff"]
        if row["staff_id"] == str(worker.id)
    ]
    assert len(rows) == 1, rows
    return rows[0]


@pytest.fixture
def general_work(superuser: Staff) -> Job:
    """The internal job clocked time on no job is swept to, as ``create_shop_jobs`` leaves it."""
    defaults = CompanyDefaults.get_solo()
    job = make_job(defaults.shop_company, superuser, name="General work", status="special")
    defaults.general_work_job = job
    defaults.save(update_fields=["general_work_job"])
    return job


@pytest.fixture
def job_y(company: Company, superuser: Staff) -> Job:
    return _job(company, superuser, "Job Y")


# ── E. Overtime ─────────────────────────────────────────────────────────


def test_E1_a_long_day_on_one_job_is_eight_ordinary_then_time_and_a_half(
    worker: Staff, job: Job
) -> None:
    """One job 07:00-17:00 with the standard breaks inside: 8h ordinary to 16:00, then 1h at 1.5x.

    Guards workshop_timesheet_service.create_entry (overtime_hours, _split_at_overtime).
    """
    _clock(worker, "07:00", "17:00")

    # 07:00-17:00 is 10h, less 0.25 + 0.5 + 0.25 of breaks = 9h.
    _drawer(worker, job, "9", "07:00", "17:00")

    assert _lines(job, worker) == [
        # 8h from 07:00 stepping over 1h of breaks ends 16:00; 48 x 1, 120 x 1.
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", False),
        # The ninth hour: 48 x 1.5 = 72, 120 x 1.5 = 180.
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_E1b_the_hour_past_eight_is_paid_through_the_overtime_earnings_rate(
    worker: Staff, job: Job
) -> None:
    """As E1: the 8h post to Xero as Ordinary Time, the hour past them as Time and one half.

    The pay item, not the multiplier, is what Xero pays by.
    Guards time_entry_rates.resolve_xero_pay_item, which each piece is priced through.
    """
    _clock(worker, "07:00", "17:00")

    _drawer(worker, job, "9", "07:00", "17:00")

    lines = CostLine.objects.filter(staff=worker, cost_set__job=job).order_by("created_at")
    assert [(line.quantity, line.xero_pay_item.name) for line in lines if line.xero_pay_item] == [
        (Decimal("8.000"), "Ordinary Time"),
        (Decimal("1.000"), "Time and one half"),
    ]


def test_E2_the_hour_past_eight_belongs_to_the_job_worked_then(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """5h on Job X, then 4h on Job Y: Y is 3h ordinary and 1h at 1.5x.

    Guards workshop_timesheet_service.overtime_hours.
    """
    _clock(worker, "07:00", "17:00")

    _drawer(worker, job, "5")
    _drawer(worker, job_y, "4")

    # X: 07:00 + 5h + 0.25 (08:30) + 0.5 (lunch) = 12:45.
    assert _lines(job, worker) == [
        ("07:00-12:45", "5.000", 1.0, 1.0, "48.00", "120.00", False),
    ]
    # Y: 8 - 5 = 3h ordinary from 12:45 + 0.25 (13:30) = 16:00; 4 - 3 = 1h at 1.5x to 17:00.
    assert _lines(job_y, worker) == [
        ("12:45-16:00", "3.000", 1.0, 1.0, "48.00", "120.00", False),
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_E3_saved_in_reverse_the_later_entry_carries_the_overtime(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """4h on Y first, then 5h on X: X is 4h ordinary and 1h at 1.5x. Order of saving decides.

    Guards workshop_timesheet_service.overtime_hours.
    """
    _clock(worker, "07:00", "17:00")

    _drawer(worker, job_y, "4")
    _drawer(worker, job, "5")

    # Y: 07:00 + 4h + 0.25 (08:30) = 11:15.
    assert _lines(job_y, worker) == [
        ("07:00-11:15", "4.000", 1.0, 1.0, "48.00", "120.00", False),
    ]
    # X: 8 - 4 = 4h ordinary from 11:15 + 0.5 (lunch) + 0.25 (13:30) = 16:00; then 1h at 1.5x.
    assert _lines(job, worker) == [
        ("11:15-16:00", "4.000", 1.0, 1.0, "48.00", "120.00", False),
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_E4_the_drawer_warns_two_hours_of_a_ten_hour_task_are_overtime(
    worker_client: Client, worker: Staff
) -> None:
    """A 10h task with no start typed: the drawer is told 2h will be overtime before saving.

    Guards api.timesheets_my_day_placement and workshop_timesheet_service.overtime_hours.
    """
    _clock(worker, "07:00", "17:00")

    asked = worker_client.get(f"{PLACEMENT_URL}?date={DAY.isoformat()}&hours=10")

    assert asked.status_code == 200, asked.content
    # Starts at his clock-in, 07:00; 10h + 1h of breaks ends 18:00; 10 - 8 = 2h past his day.
    assert asked.json() == {
        "start": "07:00:00",
        "finish": "18:00:00",
        "hours": 10.0,
        "overtime_hours": 2.0,
    }


def test_E4b_the_drawer_is_told_the_overtime_the_save_will_make(
    worker: Staff, worker_client: Client, job: Job, company: Company, superuser: Staff
) -> None:
    """Asked as the drawer asks, placement answers what saving would put at overtime.

    8.1h is kept whole at 1x (a few minutes past 8 is not split off), and
    hours on a leave job are never overtime: he is not asked about either.
    Guards the placement endpoint's use of workshop_timesheet_service.overtime_part.
    """
    leave = make_leave_job(company, superuser, "Annual Leave")
    _clock(worker, "07:00", "17:00")

    a_little_past = worker_client.get(
        f"{PLACEMENT_URL}?date={DAY.isoformat()}&hours=8.1&job_id={job.id}"
    )
    on_leave = worker_client.get(
        f"{PLACEMENT_URL}?date={DAY.isoformat()}&hours=10&job_id={leave.id}"
    )

    assert a_little_past.status_code == 200, a_little_past.content
    assert a_little_past.json()["overtime_hours"] == 0.0
    assert on_leave.status_code == 200, on_leave.content
    assert on_leave.json()["overtime_hours"] == 0.0


def test_E5_a_rate_he_chose_stands_and_nothing_is_split(worker: Staff, job: Job) -> None:
    """A 10h task he saves at 2x on purpose: one line at 2x, nothing split.

    Guards workshop_timesheet_service.create_entry (a chosen rate skips the split).
    """
    _clock(worker, "07:00", "18:00")

    # 07:00-18:00 is 11h less 1h of breaks = 10h.
    _drawer(worker, job, "10", "07:00", "18:00", rate="2.0")

    # 48 x 2 = 96; 120 x 2 = 240.
    assert _lines(job, worker) == [
        ("07:00-18:00", "10.000", 2.0, 2.0, "96.00", "240.00", False),
    ]


def test_E6_unpaid_time_entered_long_stays_unpaid_and_is_never_overtime(
    worker: Staff, job: Job
) -> None:
    """0x (unpaid) time entered long: stays unpaid, never overtime.

    Guards workshop_timesheet_service.create_entry (only ordinary time is split).
    """
    _clock(worker, "07:00", "17:00")

    _drawer(worker, job, "9", "07:00", "17:00", rate="0.0")

    # 48 x 0 = 0; the charge tracks the wage, 120 x 0 = 0.
    assert _lines(job, worker) == [
        ("07:00-17:00", "9.000", 0.0, 0.0, "0.00", "0.00", False),
    ]


def test_E7_the_fill_sheet_row_that_crosses_eight_is_split(worker: Staff, job: Job) -> None:
    """The fill-day sheet: three rows totalling 9h, none ticked: the part past 8 is at 1.5x.

    Guards day_submission.submit_day through workshop_timesheet_service.create_entry.
    """
    _clock(worker, "07:00", "17:00")

    day_submission.submit_day(
        worker,
        DAY,
        [
            {"job_id": job.id, "hours": Decimal("3"), "description": None, "time_and_a_half": False}
            for _ in range(3)
        ],
        None,
        timezone.now(),
    )

    assert _lines(job, worker) == [
        # 07:00 + 3h + 0.25 (08:30) = 10:15.
        ("07:00-10:15", "3.000", 1.0, 1.0, "48.00", "120.00", False),
        # 10:15 + 3h + 0.5 (lunch) + 0.25 (13:30) = 14:00.
        ("10:15-14:00", "3.000", 1.0, 1.0, "48.00", "120.00", False),
        # 6 done, 2 to the 8: 14:00-16:00 ordinary, then 1h at 1.5x to 17:00.
        ("14:00-16:00", "2.000", 1.0, 1.0, "48.00", "120.00", False),
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_E8_a_fill_row_ticked_time_and_a_half_is_that_rate_whatever_the_total(
    worker: Staff, job: Job
) -> None:
    """A fill-day row ticked time and a half: that row is 1.5x whatever the total.

    Guards day_submission.submit_day (the tick sets the wage multiplier).
    """
    _clock(worker, "07:00", "15:00")

    day_submission.submit_day(
        worker,
        DAY,
        [{"job_id": job.id, "hours": Decimal("2"), "description": None, "time_and_a_half": True}],
        None,
        timezone.now(),
    )

    # 07:00 + 2h + 0.25 (08:30) = 09:15; 48 x 1.5 = 72, 120 x 1.5 = 180.
    assert _lines(job, worker) == [
        ("07:00-09:15", "2.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_E9_an_edit_that_takes_six_hours_to_nine_does_not_re_rate(worker: Staff, job: Job) -> None:
    """An edit takes a 6h entry to 9h: no re-rating, 9h ordinary. The office checks.

    Guards workshop_timesheet_service.update_entry.
    """
    _clock(worker, "07:00", "17:00")
    # 07:00 + 6h + 1h of breaks = 14:00.
    _drawer(worker, job, "6", "07:00", "14:00")
    (line,) = _line_ids(job, worker)

    workshop_timesheet_service.update_entry(worker, {"entry_id": line.id, "hours": Decimal("9")})

    # The finish is redrawn: 07:00 + 9h + 1h of breaks = 17:00; still 1x.
    assert _lines(job, worker) == [
        ("07:00-17:00", "9.000", 1.0, 1.0, "48.00", "120.00", False),
    ]


def test_E10_overtime_left_on_a_short_day_stands_and_approve_time_flags_it(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """5h on X, 4h on Y (1h of Y at 1.5x), then he deletes X: Y's overtime hour stays at 1.5x.

    Edits never re-rate; Approve time flags overtime on a day under 8h (``overtime_check``).
    Guards workshop_timesheet_service.delete_entry and approval.day_approvals.
    """
    _clock(worker, "07:00", "17:00")
    _drawer(worker, job, "5")
    _drawer(worker, job_y, "4")
    (x,) = _line_ids(job, worker)

    workshop_timesheet_service.delete_entry(worker, x.id)

    # As in E2: Y 12:45-16:00 ordinary, 16:00-17:00 at 1.5x, untouched by the delete.
    assert _lines(job_y, worker) == [
        ("12:45-16:00", "3.000", 1.0, 1.0, "48.00", "120.00", False),
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]
    # 4h on jobs, 1h of it at 1.5x: overtime on a day under 8h.
    assert _approval_row(DAY, worker)["overtime_check"] is True


def test_E11_a_weekend_has_no_usual_day_so_ten_hours_are_as_entered(
    worker: Staff, job: Job
) -> None:
    """Weekend, 10h: as entered, since there is no usual day.

    Guards workshop_timesheet_service.overtime_hours (no standard day on a weekend).
    """
    # 07:00-17:00 on a Saturday with no breaks on it: 10h.
    _drawer(worker, job, "10", "07:00", "17:00", day=SATURDAY)

    assert _lines(job, worker) == [
        ("07:00-17:00", "10.000", 1.0, 1.0, "48.00", "120.00", False),
    ]


def test_E12_breaks_are_never_overtime(worker: Staff, job: Job, break_job: Job) -> None:
    """Breaks are never overtime, paid or unpaid, even one added after the day passed 8h.

    Guards workshop_timesheet_service.create_entry (a break is never split or re-rated).
    """
    _clock(worker, "07:00", "17:00")
    _drawer(worker, job, "9", "07:00", "17:00")

    attendance.add_break(worker, DAY, T("16:15"), T("16:30"), paid=True, actor=worker)

    breaks = sorted(_lines(break_job, worker))
    # Paid breaks: 48 x 1 = 48, lunch 48 x 0 = 0; the Break job bills nobody.
    assert breaks == [
        ("08:30-08:45", "0.250", 1.0, 0.0, "48.00", "0.00", False),
        ("11:30-12:00", "0.500", 0.0, 0.0, "0.00", "0.00", False),
        ("13:30-13:45", "0.250", 1.0, 0.0, "48.00", "0.00", False),
        ("16:15-16:30", "0.250", 1.0, 0.0, "48.00", "0.00", False),
    ]


def test_E13_leave_is_not_work_so_four_hours_leave_and_six_worked_is_no_overtime(
    worker: Staff, job: Job, company: Company, superuser: Staff
) -> None:
    """Leave 4h plus 6h on jobs: no overtime, leave isn't work.

    Part of a day's leave is time entered on the leave job (owner, 2026-10-25:
    the leave screen books whole days; "for anything less, you enter time on
    the leave job").

    Guards workshop_timesheet_service.overtime_hours (leave is left out of the day's work).
    """
    leave_job = make_leave_job(company, superuser, "Annual Leave")
    _drawer(worker, leave_job, "4")

    _drawer(worker, job, "6")

    # Unclocked: his turn starts after the leave's 07:00-11:15 (4h + the 08:30
    # break), so 6h + lunch + the 13:30 break runs 11:15-18:00, all ordinary.
    assert [(line[1], line[2]) for line in _lines(job, worker)] == [("6.000", 1.0)]


def test_E13b_ten_hours_on_the_leave_job_is_never_split_into_overtime(
    worker: Staff, company: Company, superuser: Staff
) -> None:
    """Leave is paid at its own rate in Xero, so none of it is time and a half.

    Guards workshop_timesheet_service.overtime_part (a leave job is not work).
    """
    leave_job = make_leave_job(company, superuser, "Annual Leave")

    _drawer(worker, leave_job, "10")

    assert [(line[1], line[2]) for line in _lines(leave_job, worker)] == [("10.000", 1.0)]


def test_E13d_a_few_minutes_past_eight_left_ordinary_raises_no_overtime_check(
    worker: Staff, job: Job
) -> None:
    """He enters 8.1h: the 0.1h past 8 is under a quarter hour, so the entry stays whole at 1x.

    That is the split rule working, not a day for the office to check.
    Guards approval._overtime_is_off.
    """
    _clock(worker, "07:00", "17:00")

    _drawer(worker, job, "8.1")

    assert [rate for _, _, rate, *_ in _lines(job, worker)] == [1.0]
    assert _approval_row(DAY, worker)["overtime_check"] is False


def test_E13c_leave_entered_on_the_leave_job_raises_no_overtime_check(
    worker: Staff, job: Job, company: Company, superuser: Staff
) -> None:
    """4h on the leave job and 6h worked: nothing is past the usual day, nothing to check.

    Guards approval._overtime_is_off (leave is left out of the day's work).
    """
    leave_job = make_leave_job(company, superuser, "Annual Leave")
    _drawer(worker, leave_job, "4")
    _drawer(worker, job, "6")

    assert _approval_row(DAY, worker)["overtime_check"] is False


def test_E14_nine_hours_entered_in_the_office_grid_is_eight_then_one_at_time_and_a_half(
    office_staff: Staff, worker: Staff, job: Job
) -> None:
    """The office enters 9h for him in the office grid: the same rule, 1h past 8 is 1.5x.

    Guards job_service.create_cost_line (the grid's write path).
    """
    _grid(office_staff, job, worker, "9", bill=1.0)

    # Placed from 07:00 around the breaks, as from his phone. Office-entered
    # time waits for approval like any.
    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", False),
        # 9 - 8 = 1h: 48 x 1.5 = 72, charged by default at 120 x 1.5 = 180.
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_E15_twelve_hours_after_five_past_midnight_is_three_ordinary_and_nine_overtime(
    worker: Staff, job: Job
) -> None:
    """12h after 5h, running past midnight: 3h ordinary and 9h at 1.5x, both without times.

    Guards workshop_timesheet_service._split_at_overtime (no times past midnight).
    """
    _clock(worker, "07:00", "17:00")
    _drawer(worker, job, "5")

    # From 12:45, 12h + 0.25 (13:30) ends 01:00 the next day: no picture.
    _drawer(worker, job, "12")

    assert _lines(job, worker) == [
        ("07:00-12:45", "5.000", 1.0, 1.0, "48.00", "120.00", False),
        # 8 - 5 = 3 ordinary; 12 - 3 = 9 at 1.5x.
        ("untimed", "3.000", 1.0, 1.0, "48.00", "120.00", False),
        ("untimed", "9.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_E16_swept_general_work_past_eight_is_paid_time_and_a_half_and_billed_nothing(
    office_staff: Staff, worker: Staff, general_work: Job
) -> None:
    """Swept General work past 8h: paid 1.5x, charged nothing (shop job).

    Guards workshop_timesheet_service.refill_general_work (through create_entry).
    """
    _clock(worker, "07:00", "17:00")

    approval.sweep_person(worker, [DAY], office_staff)

    # The stretches between his breaks; General work bills nobody, so every unit_rev is 0.
    assert _lines(general_work, worker) == [
        ("07:00-08:30", "1.500", 1.0, 0.0, "48.00", "0.00", True),
        ("08:45-11:30", "2.750", 1.0, 0.0, "48.00", "0.00", True),
        ("12:00-13:30", "1.500", 1.0, 0.0, "48.00", "0.00", True),
        # 1.5 + 2.75 + 1.5 = 5.75 done; 13:45-17:00 is 3.25: 2.25 ordinary to 16:00, 1h past 8.
        ("13:45-16:00", "2.250", 1.0, 0.0, "48.00", "0.00", True),
        ("16:00-17:00", "1.000", 1.5, 0.0, "72.00", "0.00", True),
    ]


def test_E17_a_non_billable_entry_crossing_eight_bills_none_of_its_overtime(
    worker: Staff, job: Job
) -> None:
    """A non-billable entry crossing 8h: the 1.5x part is still not billed.

    Guards workshop_timesheet_service._split_at_overtime (the split keeps is_billable).
    """
    _clock(worker, "07:00", "17:00")

    _drawer(worker, job, "9", "07:00", "17:00", billable=False)

    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 0.0, "48.00", "0.00", False),
        # 48 x 1.5 = 72; not billable, 120 x 0 = 0.
        ("16:00-17:00", "1.000", 1.5, 0.0, "72.00", "0.00", False),
    ]


# ── F. Urgent jobs ──────────────────────────────────────────────────────


def test_F1b_setting_an_urgent_hour_back_to_ordinary_pay_keeps_its_urgent_charge(
    office_staff: Staff, superuser: Staff, worker: Staff, job: Job
) -> None:
    """9h on an urgent job, so 1h at time and a half; the office pays that hour ordinary.

    The wage goes to 1x; the charge stays 1.5x, an urgent job's charge (owner).
    Guards workshop_timesheet_service.update_entry's re-derived charge.
    """
    _make_urgent(job, superuser)
    _clock(worker, "07:00", "17:00")
    _drawer(worker, job, "9", "07:00", "17:00")
    late = CostLine.objects.get(staff=worker, cost_set__job=job, quantity=Decimal("1.000"))

    workshop_timesheet_service.update_entry(
        office_staff, {"entry_id": late.id, "wage_rate_multiplier": Decimal("1.0")}
    )

    late.refresh_from_db()
    # 48 x 1 = 48; 120 x 1.5 = 180.
    assert (late.meta["wage_rate_multiplier"], late.meta["bill_rate_multiplier"]) == (1.0, 1.5)
    assert (late.unit_cost, late.unit_rev) == (Decimal("48.00"), Decimal("180.00"))


def test_F1_the_office_grid_charges_an_urgent_job_at_time_and_a_half(
    office_staff: Staff, superuser: Staff, worker: Staff, job: Job
) -> None:
    """The office grid, entry on an urgent job: the Invoice multiplier defaults to 1.5x, wage 1x.

    The grid's job pick (timesheetDraft.applyJobPick) sends bill 1.5 for an urgent job.
    Guards job_service.create_cost_line pricing an explicit bill multiplier.
    """
    _make_urgent(job, superuser)

    _grid(office_staff, job, worker, "2", bill=1.5)

    # 48 x 1 = 48; 120 x 1.5 = 180. Placed from 07:00, around the 08:30 break.
    assert _lines(job, worker) == [
        ("07:00-09:15", "2.000", 1.0, 1.5, "48.00", "180.00", False),
    ]


def test_F2_a_drawer_entry_on_an_urgent_job_is_charged_time_and_a_half(
    superuser: Staff, worker: Staff, job: Job
) -> None:
    """The drawer, a worker's entry on an urgent job: charged 1.5x, as the grid would.

    Proposed (⚠): the same default as the grid, so it doesn't depend on who typed it.
    Guards workshop_timesheet_service.create_entry.
    """
    _make_urgent(job, superuser)
    _clock(worker, "07:00", "15:00")

    # 09:00-11:00 holds no break: 2h.
    _drawer(worker, job, "2", "09:00", "11:00")

    # Wage 48 x 1 = 48; charge 120 x 1.5 = 180.
    assert _lines(job, worker) == [
        ("09:00-11:00", "2.000", 1.0, 1.5, "48.00", "180.00", False),
    ]


def test_F3_overtime_on_an_urgent_job_is_charged_time_and_a_half_not_two_and_a_quarter(
    superuser: Staff, worker: Staff, job: Job
) -> None:
    """Overtime on an urgent job: paid 1.5x and charged 1.5x, not 2.25x. The higher applies.

    Proposed (⚠). Guards workshop_timesheet_service.create_entry and _split_at_overtime.
    """
    _make_urgent(job, superuser)
    _clock(worker, "07:00", "17:00")

    _drawer(worker, job, "9", "07:00", "17:00")

    assert _lines(job, worker) == [
        # Ordinary hours on an urgent job: 48 x 1, charged 120 x 1.5 = 180.
        ("07:00-16:00", "8.000", 1.0, 1.5, "48.00", "180.00", False),
        # The hour past 8: 48 x 1.5 = 72; charged the higher of 1.5 and 1.5,
        # 120 x 1.5 = 180, never 120 x 2.25 = 270.
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_F4_the_office_lowering_the_charge_when_approving_stands(
    office_staff: Staff, superuser: Staff, worker: Staff, job: Job
) -> None:
    """The office lowers the charge on an urgent entry when approving: it stands, billed as set.

    Guards workshop_timesheet_service.update_entry and approval.approve_day.
    """
    _make_urgent(job, superuser)
    _clock(worker, "07:00", "15:00")
    _drawer(worker, job, "2", "09:00", "11:00", bill="1.5")
    (line,) = _line_ids(job, worker)

    workshop_timesheet_service.update_entry(
        office_staff, {"entry_id": line.id, "bill_rate_multiplier": Decimal("1.0")}
    )
    approval.approve_day(worker, DAY, office_staff)

    # 48 x 1 = 48; lowered to 120 x 1 = 120; approved.
    assert _lines(job, worker) == [
        ("09:00-11:00", "2.000", 1.0, 1.0, "48.00", "120.00", True),
    ]


# ── P. Overtime, the hairy cases ────────────────────────────────────────


def test_P1_half_an_hour_after_seven_and_three_quarters_is_split_in_half(
    worker: Staff, job: Job
) -> None:
    """He already has 7.75h, then enters 0.5h: 0.25h ordinary and 0.25h at 1.5x.

    Guards workshop_timesheet_service.overtime_hours and _split_at_overtime.
    """
    _clock(worker, "07:00", "17:00")
    _drawer(worker, job, "7.75")

    _drawer(worker, job, "0.5")

    assert _lines(job, worker) == [
        # 07:00 + 7.75h + 1h of breaks = 15:45.
        ("07:00-15:45", "7.750", 1.0, 1.0, "48.00", "120.00", False),
        # 8 - 7.75 = 0.25 ordinary to 16:00; 0.5 - 0.25 = 0.25 at 1.5x to 16:15.
        ("15:45-16:00", "0.250", 1.0, 1.0, "48.00", "120.00", False),
        ("16:00-16:15", "0.250", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_P2_no_line_under_a_quarter_hour_is_split_off(worker: Staff, job: Job) -> None:
    """He already has 7.98h, then enters 1h: no 0.02h line; the whole hour takes 1.5x.

    Proposed (⚠): the whole entry takes the rate its larger part has (0.98h past 8).
    Guards workshop_timesheet_service._split_at_overtime.
    """
    _clock(worker, "07:00", "17:00")
    # 07:00-16:00 is 9h less 1h of breaks = 8h of span, holding 7.98h.
    _drawer(worker, job, "7.98", "07:00", "16:00")

    _drawer(worker, job, "1", "16:00", "17:00")

    assert _lines(job, worker) == [
        ("07:00-16:00", "7.980", 1.0, 1.0, "48.00", "120.00", False),
        # 0.02h ordinary + 0.98h past 8: the larger part's rate, 1.5x, for the whole hour.
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_P3_exactly_eight_hours_has_no_overtime_line(worker: Staff, job: Job) -> None:
    """Exactly 8.00h: no overtime line.

    Guards workshop_timesheet_service.overtime_hours (the boundary).
    """
    _clock(worker, "07:00", "16:00")

    # 07:00-16:00 is 9h less 1h of breaks = 8h.
    _drawer(worker, job, "8", "07:00", "16:00")

    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", False),
    ]


def test_P4_on_a_short_friday_overtime_starts_after_five_hours(
    manage_client: Client, worker: Staff, job: Job
) -> None:
    """Friday's usual day is 07:00-12:00: on Friday, overtime starts after 5h on jobs.

    Guards workshop_timesheet_service.overtime_hours (the weekday's own usual day).
    """
    saved = manage_client.patch(
        DEFAULTS_URL, data={"fri_end": "12:00:00"}, content_type="application/json"
    )
    assert saved.status_code == 200, saved.content
    # Clocked to 13:00: the 08:30 break and lunch go on; the 13:30 break is after he left.
    _clock(worker, "07:00", "13:00", day=FRIDAY)

    # 07:00-13:00 is 6h less 0.25 + 0.5 of breaks = 5.25h.
    _drawer(worker, job, "5.25", "07:00", "13:00", day=FRIDAY)

    assert _lines(job, worker) == [
        # 5h from 07:00 + 0.75h of breaks = 12:45.
        ("07:00-12:45", "5.000", 1.0, 1.0, "48.00", "120.00", False),
        # 5.25 - 5 = 0.25h at 1.5x.
        ("12:45-13:00", "0.250", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_P5_changing_the_usual_day_never_re_rates_existing_lines(
    manage_client: Client, worker: Staff, job: Job
) -> None:
    """The company changes Monday's hours after entries exist: existing lines are never re-rated.

    Guards the company-defaults save leaving priced time lines alone.
    """
    _clock(worker, "07:00", "16:00")
    _drawer(worker, job, "8", "07:00", "16:00")

    saved = manage_client.patch(
        DEFAULTS_URL, data={"mon_end": "14:00:00"}, content_type="application/json"
    )

    assert saved.status_code == 200, saved.content
    # Monday is now 7h, but the 8h saved under the old day stays ordinary.
    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", False),
    ]


def test_P6_ticked_time_and_a_half_rows_count_toward_the_eight(worker: Staff, job: Job) -> None:
    """Fill sheet: 6h unticked, 2h ticked 1.5x, 2h unticked: the last 2h are 1.5x, never 2.25x.

    Proposed (⚠): the ticked 2h counts toward the 8. The day is 6h ordinary and 4h at 1.5x.
    Guards day_submission.submit_day through workshop_timesheet_service.overtime_hours.
    """
    _clock(worker, "07:00", "18:00")

    day_submission.submit_day(
        worker,
        DAY,
        [
            {
                "job_id": job.id,
                "hours": Decimal("6"),
                "description": None,
                "time_and_a_half": False,
            },
            {"job_id": job.id, "hours": Decimal("2"), "description": None, "time_and_a_half": True},
            {
                "job_id": job.id,
                "hours": Decimal("2"),
                "description": None,
                "time_and_a_half": False,
            },
        ],
        None,
        timezone.now(),
    )

    assert _lines(job, worker) == [
        # 07:00 + 6h + 1h of breaks = 14:00.
        ("07:00-14:00", "6.000", 1.0, 1.0, "48.00", "120.00", False),
        ("14:00-16:00", "2.000", 1.5, 1.5, "72.00", "180.00", False),
        # 6 + 2 = 8 already: all of this row is past 8, 1.5x (48 x 1.5, 120 x 1.5).
        ("16:00-18:00", "2.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def _split_day(worker: Staff, job: Job) -> tuple[CostLine, CostLine]:
    """07:00-17:00 on one job, saved from the drawer and split at 8h (E1)."""
    _clock(worker, "07:00", "17:00")
    _drawer(worker, job, "9", "07:00", "17:00")
    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", False),
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ], "the day did not split at 8h"
    ordinary, late = _line_ids(job, worker)
    return ordinary, late


def test_P7_deleting_the_ordinary_half_leaves_the_overtime_half_flagged(
    office_staff: Staff, worker: Staff, job: Job
) -> None:
    """The office deletes the ordinary half of a split entry: the 1.5x half stays, flagged.

    Guards workshop_timesheet_service.delete_entry and approval.day_approvals (``overtime_check``).
    """
    ordinary, _late = _split_day(worker, job)

    workshop_timesheet_service.delete_entry(office_staff, ordinary.id)

    assert _lines(job, worker) == [
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", False),
    ]
    # 1h on jobs, all of it at 1.5x: overtime on a day under 8h.
    assert _approval_row(DAY, worker)["overtime_check"] is True


def test_P8_the_office_lowering_the_overtime_half_to_ordinary_stands(
    office_staff: Staff, worker: Staff, job: Job
) -> None:
    """The office lowers the 1.5x half to ordinary when checking: it stands, priced and charged 1x.

    Guards workshop_timesheet_service.update_entry and approval.approve_day.
    """
    _ordinary, late = _split_day(worker, job)

    workshop_timesheet_service.update_entry(
        office_staff, {"entry_id": late.id, "wage_rate_multiplier": Decimal("1.0")}
    )
    approval.approve_day(worker, DAY, office_staff)

    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", True),
        # Lowered: 48 x 1 = 48, the charge follows the wage, 120 x 1 = 120.
        ("16:00-17:00", "1.000", 1.0, 1.0, "48.00", "120.00", True),
    ]


def test_P9_hours_worked_on_a_public_holiday_default_to_time_and_a_half(
    company: Company, superuser: Staff, worker: Staff, job: Job
) -> None:
    """He works on a public holiday: every hour defaults to 1.5x.

    Proposed (⚠). A public holiday is known by the office closure's public-holiday
    line on the date (LeaveType PUBLIC_HOLIDAY), the only holiday record there is.
    Guards workshop_timesheet_service.create_entry.
    """
    make_public_holiday_job(company, superuser)
    leave_service.create_office_closure(
        start_date=DAY, end_date=DAY, note="Public holiday", actor=superuser
    )

    # Unclocked: 09:00-11:00 holds no break, 2h.
    _drawer(worker, job, "2", "09:00", "11:00")

    # 48 x 1.5 = 72; 120 x 1.5 = 180.
    assert _lines(job, worker) == [
        ("09:00-11:00", "2.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


def test_P10_a_weekend_he_forgot_to_tick_stays_ordinary(worker: Staff, job: Job) -> None:
    """On a weekend he forgets to tick 1.5x: it stays ordinary. The office checks.

    Guards day_submission.submit_day (nothing works the weekend rate out).
    """
    # Clocked on Saturday: the clock puts the three standard breaks on the day.
    _clock(worker, "07:00", "16:00", day=SATURDAY)

    day_submission.submit_day(
        worker,
        SATURDAY,
        [{"job_id": job.id, "hours": Decimal("8"), "description": None, "time_and_a_half": False}],
        None,
        timezone.now(),
    )

    # 07:00 + 8h + 1h of breaks = 16:00; no usual day on a Saturday, so 1x throughout.
    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", False),
    ]


def test_P11_the_sweep_after_an_overtime_split_is_all_time_and_a_half(
    office_staff: Staff, worker: Staff, job: Job, general_work: Job
) -> None:
    """The sweep after an overtime split: the General work it adds is past 8h, so all 1.5x.

    Guards workshop_timesheet_service.refill_general_work (through overtime_hours).
    """
    _clock(worker, "07:00", "18:00")
    _drawer(worker, job, "9", "07:00", "17:00")

    approval.sweep_person(worker, [DAY], office_staff)

    # The sweep approves his own day with it.
    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", True),
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "180.00", True),
    ]
    # 17:00-18:00 on no job, 9h already done: 48 x 1.5 = 72, billed nothing.
    assert _lines(general_work, worker) == [
        ("17:00-18:00", "1.000", 1.5, 0.0, "72.00", "0.00", True),
    ]


def test_P12_eight_hours_leave_and_two_worked_is_no_overtime(
    company: Company, superuser: Staff, worker: Staff, job: Job
) -> None:
    """8h of leave plus 2h on jobs: no overtime. Paid 10h: leave through Xero leave, 2h ordinary.

    Guards workshop_timesheet_service.overtime_hours (leave is left out of the day's work).
    """
    leave_job = make_leave_job(company, superuser, "Annual Leave")
    leave_service.create_leave_request(
        staff_id=worker.id,
        leave_type_code=LeaveType.Code.ANNUAL,
        start_date=DAY,
        end_date=DAY,
        note=None,
        requested_days=[DAY],
        actor=superuser,
    )

    _drawer(worker, job, "2")

    # Unclocked: from the standard 07:00, 2h + 0.25 (08:30) = 09:15, ordinary.
    assert _lines(job, worker) == [
        ("07:00-09:15", "2.000", 1.0, 1.0, "48.00", "120.00", False),
    ]
    # Leave: 8h paid at 48 x 1, never billed, approved as it is made.
    assert _lines(leave_job, worker) == [
        ("untimed", "8.000", 1.0, 0.0, "48.00", "0.00", True),
    ]


def test_P13_an_overtime_line_past_midnight_keeps_no_times_and_stays_time_and_a_half(
    worker: Staff, job: Job
) -> None:
    """An overtime line that runs past midnight is kept without times, still 1.5x.

    Guards workshop_timesheet_service.create_entry (all-overtime entry with no picture).
    """
    _clock(worker, "07:00", "16:00")
    _drawer(worker, job, "8", "07:00", "16:00")

    # From 16:00, 10h ends 02:00 the next day: no picture. 8h already done: all 10h past 8.
    _drawer(worker, job, "10")

    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", False),
        ("untimed", "10.000", 1.5, 1.5, "72.00", "180.00", False),
    ]


# ── N, O, U ─────────────────────────────────────────────────────────────


def test_N4_a_salaried_persons_long_day_is_not_split(worker: Staff, job: Job) -> None:
    """A salaried person works 9h: no overtime split. The charge follows the urgent/default rule.

    Proposed (⚠). Guards workshop_timesheet_service.create_entry (overtime_hours for pay_basis).
    """
    worker.pay_basis = "salary"
    worker.save(update_fields=["pay_basis", "updated_at"])
    CompanyDefaults.objects.update(labour_cost_loading=Decimal("20.00"))
    StaffPayrollTerm.objects.create(
        staff=worker,
        effective_from=date(2026, 1, 1),
        pay_basis="salary",
        annual_salary=Decimal("104000.00"),
        working_weeks=[
            {
                "monday": 8,
                "tuesday": 8,
                "wednesday": 8,
                "thursday": 8,
                "friday": 8,
                "saturday": 0,
                "sunday": 0,
            }
        ],
    )
    _clock(worker, "07:00", "17:00")

    _drawer(worker, job, "9", "07:00", "17:00")

    # Salary cost: 104000 / 52 / 40 = 50, plus 20% loading = 60.00 an hour, at 1x.
    # Not an urgent job: charged 120 x 1.
    assert _lines(job, worker) == [
        ("07:00-17:00", "9.000", 1.0, 1.0, "60.00", "120.00", False),
    ]


def test_O3_an_overtime_line_moved_to_another_job_is_repriced_there_and_still_overtime(
    company: Company, office_staff: Staff, superuser: Staff, worker: Staff, job: Job
) -> None:
    """The office moves an overtime line to another job: repriced at its rate, still 1.5x.

    Guards workshop_timesheet_service.update_entry (job_id) and job_service.move_time_line.
    """
    destination = _job(company, superuser, "Destination", rate="200.00")
    _ordinary, late = _split_day(worker, job)

    workshop_timesheet_service.update_entry(
        office_staff, {"entry_id": late.id, "job_id": destination.id}
    )

    assert _lines(job, worker) == [
        ("07:00-16:00", "8.000", 1.0, 1.0, "48.00", "120.00", False),
    ]
    # 48 x 1.5 = 72; the destination's 200 x 1.5 = 300.
    assert _lines(destination, worker) == [
        ("16:00-17:00", "1.000", 1.5, 1.5, "72.00", "300.00", False),
    ]


def test_O5_a_job_made_urgent_charges_new_entries_more_and_leaves_old_ones(
    superuser: Staff, worker: Staff, job: Job
) -> None:
    """A job made urgent after entries exist: existing entries not re-charged; new ones 1.5x.

    Guards workshop_timesheet_service.create_entry (urgent default) and Job.save.
    """
    _clock(worker, "07:00", "15:00")
    # 09:00-11:00 holds no break: 2h.
    _drawer(worker, job, "2", "09:00", "11:00")

    _make_urgent(job, superuser)
    # 12:00-13:00 holds no break: 1h.
    _drawer(worker, job, "1", "12:00", "13:00")

    assert _lines(job, worker) == [
        # Saved before the job was urgent: 120 x 1, untouched.
        ("09:00-11:00", "2.000", 1.0, 1.0, "48.00", "120.00", False),
        # Saved after: charged 120 x 1.5 = 180, wage still 48 x 1.
        ("12:00-13:00", "1.000", 1.0, 1.5, "48.00", "180.00", False),
    ]


def test_U3_an_overtime_line_on_a_shop_job_is_paid_more_and_billed_nothing(
    superuser: Staff, worker: Staff
) -> None:
    """An overtime line on a shop job: paid 1.5x and billed nothing.

    Guards workshop_timesheet_service._split_at_overtime on an unbillable job.
    """
    shop = make_job(CompanyDefaults.get_solo().shop_company, superuser, name="Workshop upkeep")
    _clock(worker, "07:00", "17:00")

    # The drawer sends a shop job's time as not billable.
    _drawer(worker, shop, "9", "07:00", "17:00", billable=False)

    assert _lines(shop, worker) == [
        ("07:00-16:00", "8.000", 1.0, 0.0, "48.00", "0.00", False),
        # 48 x 1.5 = 72; billed nothing.
        ("16:00-17:00", "1.000", 1.5, 0.0, "72.00", "0.00", False),
    ]
