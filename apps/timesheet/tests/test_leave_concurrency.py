"""Leave waits for whoever holds the person's day before reading or changing it."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.tests.concurrency import await_database_lock, start_database_task
from apps.job.models import Job
from apps.timesheet.models import LeaveDay, LeaveType
from apps.timesheet.services import leave_service
from apps.timesheet.tests.conftest import make_leave_job, make_time_line
from apps.timesheet.tests.test_leave_service import MONDAY, TUESDAY

pytestmark = pytest.mark.committed_db


def _book_monday(worker: Staff, company: Company, superuser: Staff) -> UUID:
    make_leave_job(company, superuser, "Annual Leave")
    created = leave_service.create_leave_request(
        staff_id=worker.id,
        leave_type_code=LeaveType.Code.ANNUAL,
        start_date=MONDAY,
        end_date=MONDAY,
        note=None,
        requested_days=[MONDAY],
        actor=superuser,
    )
    return UUID(created["request"]["id"])


def test_moving_leave_reads_his_day_after_a_sweep_has_filled_it(
    worker: Staff, company: Company, superuser: Staff, job: Job
) -> None:
    """The office moves his leave to Tuesday while a sweep is filling Tuesday.

    The leave waits for the sweep, then sees Tuesday full and is refused:
    read before, it would book 8h of leave over 8h of work, paying 16h.
    Guards leave_service.update_leave_request taking his lock before reading his day.
    """
    request_id = _book_monday(worker, company, superuser)

    def move_to_tuesday() -> object:
        return leave_service.update_leave_request(
            request_id=request_id,
            leave_type_code=LeaveType.Code.ANNUAL,
            start_date=TUESDAY,
            end_date=TUESDAY,
            note=None,
            requested_days=[TUESDAY],
            actor=superuser,
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            # The sweep holds his lock while it fills his day.
            Staff.objects.select_for_update().get(pk=worker.pk)
            pending, worker_pid = start_database_task(pool, move_to_tuesday)
            await_database_lock(pending, worker_pid)
            make_time_line(job, worker, accounting_date=TUESDAY)
        with pytest.raises(ValidationError, match="No available leave days remain"):
            pending.result(timeout=10)

    assert not LeaveDay.objects.filter(staff=worker, date=TUESDAY).exists()


def test_cancelling_leave_waits_for_a_sweep_of_his_day(
    worker: Staff, company: Company, superuser: Staff
) -> None:
    """A sweep reads his leave while it fills his day; the cancel waits until it is done.

    Guards leave_service.delete_leave_request taking his lock.
    """
    request_id = _book_monday(worker, company, superuser)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Staff.objects.select_for_update().get(pk=worker.pk)
            pending, worker_pid = start_database_task(
                pool, lambda: leave_service.delete_leave_request(request_id)
            )
            await_database_lock(pending, worker_pid)
        pending.result(timeout=10)
