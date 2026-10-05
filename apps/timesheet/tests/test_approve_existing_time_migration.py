"""The one-off approval of time entered before approval decided pay (KAN-376)."""

from decimal import Decimal

import pytest
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.tests.conftest import WEEK_START, make_time_line

pytestmark = pytest.mark.django_db

MIGRATION = ("timesheet", "0006_approve_time_entered_before_approval_bound_pay")


def _run() -> None:
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[MIGRATION]
    state = loader.project_state([MIGRATION])
    operation = next(op for op in migration.operations if isinstance(op, migrations.RunPython))
    with connection.schema_editor() as editor:
        operation.code(state.apps, editor)


def test_it_approves_worked_time_and_nothing_else(job: Job, worker: Staff) -> None:
    """Only actual time was ever paid; a material draft still waits for its stock issue."""
    worked = make_time_line(job, worker, accounting_date=WEEK_START, approved=False)
    material = CostLine(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Unissued steel",
        quantity=Decimal("1.000"),
        unit_cost=Decimal("10.00"),
        unit_rev=Decimal("15.00"),
        accounting_date=WEEK_START,
        approved=False,
    )
    material.save()

    _run()

    worked.refresh_from_db()
    material.refresh_from_db()
    assert worked.approved
    assert not material.approved
