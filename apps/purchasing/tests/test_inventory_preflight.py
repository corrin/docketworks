"""The operator's pre-deploy preflight answers what the database it runs on can answer.

A committed database is required: the command opens its own read-only transaction, and
``SET TRANSACTION ISOLATION LEVEL`` cannot follow a rollback fixture's earlier queries.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.tests.factories import make_company
from apps.company.tests.job_fixtures import make_job, seed_docketworks_prereqs
from apps.job.models.costing import CostLine
from apps.purchasing.management.commands.audit_inventory_openings import (
    LEDGER_SCHEMA_MIGRATION,
)

pytestmark = pytest.mark.committed_db


def charge_naming_absent_stock() -> None:
    """A booked position the cutover preflight refuses, so a skipped check is visible."""
    seed_docketworks_prereqs()
    staff = Staff.objects.create_user(
        office_email="preflight@example.com",
        password="s3cret-Pass!",
        first_name="Pre",
        last_name="Flight",
        is_office_staff=True,
        base_wage_rate=Decimal("40.00"),
    )
    job = make_job(make_company("Preflight Company"), staff, name="Preflight Job")
    CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Charge naming stock nobody holds",
        quantity=Decimal("2"),
        unit_cost=Decimal("15"),
        unit_rev=Decimal("22"),
        accounting_date=timezone.localdate(),
        approved=True,
        ext_refs={"stock_id": "1f0b3d64-0f4c-4a1e-9d5f-2c6c9a0f1b77"},
    )


def test_the_preflight_skips_ledger_checks_the_restored_database_cannot_answer() -> None:
    """Production restores predate the ledger tables, which is when this command is run.

    Asking for movement evidence there fails on a relation that does not exist yet, so the
    projection is reported and the movement checks are left to migrate. The charge below
    would fail the cutover preflight, so a quiet run proves those checks were skipped
    rather than merely satisfied.
    """
    charge_naming_absent_stock()
    with pytest.raises(DatabaseError, match="Job opening preflight failed"):
        call_command("audit_inventory_openings", "--preflight-only")

    app, name = LEDGER_SCHEMA_MIGRATION
    MigrationRecorder(connection).migration_qs.filter(app=app, name=name).delete()
    output = StringIO()
    call_command("audit_inventory_openings", "--preflight-only", stdout=output)

    assert "Duplicated receipt balances the cutover will empty: 0" in output.getvalue()
    assert "Ledger tables are not installed yet" in output.getvalue()
