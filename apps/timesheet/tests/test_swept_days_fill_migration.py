"""The one-off flagging of days swept before General work became a flag on the day."""

from datetime import time, timedelta

import pytest
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services import attendance
from apps.timesheet.tests import test_approval
from apps.timesheet.tests.conftest import WEEK_START, make_time_line

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job", "general_work")]

#: The one General work fixture (ADR 0039), registered in this module by name.
general_work = test_approval.general_work

MIGRATION = ("timesheet", "0013_swept_days_fill_with_general_work")


def _run() -> None:
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[MIGRATION]
    state = loader.project_state([MIGRATION])
    operation = next(op for op in migration.operations if isinstance(op, migrations.RunPython))
    with connection.schema_editor() as editor:
        operation.code(state.apps, editor)


def test_only_days_whose_sweep_is_still_on_general_work_are_flagged(
    job: Job, general_work: Job, worker: Staff
) -> None:
    """A swept line the office moved to Job X is Job X's time, so its day is not a filled one."""
    swept, moved = WEEK_START, WEEK_START + timedelta(days=1)
    for day in (swept, moved):
        attendance.set_clock_times(worker, day, time(7), time(15), worker)
    make_time_line(
        general_work,
        worker,
        accounting_date=swept,
        unit_rev="0.00",
        is_billable=False,
        source="general_work_sweep",
    )
    make_time_line(job, worker, accounting_date=moved, source="general_work_sweep")

    _run()

    flagged = dict(
        AttendanceDay.objects.filter(staff=worker).values_list("date", "general_work_fill")
    )
    assert flagged == {swept: True, moved: False}
