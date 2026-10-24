"""The one-off re-lay of lines whose times disagreed with their hours (owner, 2026-10-24)."""

from decimal import Decimal

import pytest
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.tests.conftest import WEEK_START, make_time_line

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]

MIGRATION = ("timesheet", "0012_entry_times_are_when_he_worked")


def _run() -> None:
    """Run the migration's code against the historical models, as it runs in production."""
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[MIGRATION]
    state = loader.project_state(migration.dependencies, at_end=True)
    operation = next(op for op in migration.operations if isinstance(op, migrations.RunPython))
    with connection.schema_editor() as editor:
        operation.code(state.apps, editor)


def _old_shape(line: CostLine, start: str, end: str) -> None:
    """Give a line times its hours do not fill, as the old rule allowed: past the model's check."""
    CostLine.objects.filter(pk=line.pk).update(
        meta={**line.meta, "start_time": start, "end_time": end}
    )


def _spans(worker: Staff, job: Job) -> list[tuple[str, str, Decimal]]:
    return sorted(
        (line.meta["start_time"], line.meta["end_time"], line.quantity)
        for line in CostLine.objects.filter(staff=worker, cost_set__job=job)
    )


def test_an_entry_stepping_over_a_break_becomes_an_entry_per_stretch(
    job: Job, worker: Staff
) -> None:
    """Four hours from 07:00 drawn as 07:00-11:15 went over the planned 08:30 break."""
    line = make_time_line(job, worker, accounting_date=WEEK_START, hours="4.000")
    _old_shape(line, "07:00:00", "11:15:00")

    _run()

    assert _spans(worker, job) == [
        ("07:00:00", "08:30:00", Decimal("1.500")),
        ("08:45:00", "11:15:00", Decimal("2.500")),
    ]
    assert sum(each.quantity for each in CostLine.objects.filter(staff=worker)) == Decimal("4")


def test_a_line_whose_hours_do_not_fit_its_times_keeps_its_hours(job: Job, worker: Staff) -> None:
    """The old rule's truth is the hours: 1.5h drawn 15:00-19:00 is 15:00-16:30."""
    line = make_time_line(job, worker, accounting_date=WEEK_START, hours="1.500")
    _old_shape(line, "15:00:00", "19:00:00")

    _run()

    assert _spans(worker, job) == [("15:00:00", "16:30:00", Decimal("1.500"))]


def test_hours_that_would_run_past_midnight_keep_no_times(job: Job, worker: Staff) -> None:
    line = make_time_line(job, worker, accounting_date=WEEK_START, hours="5.000")
    _old_shape(line, "20:00:00", "21:00:00")

    _run()

    line.refresh_from_db()
    assert (line.meta["start_time"], line.meta["end_time"], line.quantity) == (
        None,
        None,
        Decimal("5.000"),
    )


def test_a_line_that_already_agrees_is_left_alone(job: Job, worker: Staff) -> None:
    line = make_time_line(
        job,
        worker,
        accounting_date=WEEK_START,
        hours="1.000",
        start_time="15:00:00",
        end_time="16:00:00",
    )
    before = (line.meta, line.quantity, line.updated_at)

    _run()

    line.refresh_from_db()
    assert (line.meta, line.quantity, line.updated_at) == before
