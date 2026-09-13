"""Real commits must not lose contributions or publish a stale rebuilt summary."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job, make_material_line
from apps.core.tests.concurrency import await_database_lock, start_database_task
from apps.job.models import CostSet, Job

pytestmark = pytest.mark.committed_db


@pytest.mark.parametrize("repair", [False, True])
def test_concurrent_write_or_rebuild_sees_the_committed_contribution(
    job: Job, repair: bool
) -> None:
    """A rebuild that reads before locking can overwrite a just-committed contribution."""
    line = make_material_line(job, cost="10", rev="0")
    cost_set = line.cost_set
    if repair:
        CostSet.objects.filter(pk=cost_set.id).update(summary={"cost": 999, "rev": 0, "hours": 0})

    def change() -> None:
        if repair:
            cost_set.recalculate_summary()
        else:
            make_material_line(job, cost="20", rev="0")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            line.quantity = Decimal("2")
            line.save()
            pending, worker_pid = start_database_task(pool, change)
            await_database_lock(pending, worker_pid)
        pending.result(timeout=10)
    cost_set.refresh_from_db()
    assert cost_set.summary["cost"] == (20 if repair else 40)
    assert cost_set.summary_is_current()


def test_opposite_transfers_keep_both_jobs_correct(
    job: Job, company: Company, office_staff: Staff
) -> None:
    """Two transfers must subtract each source and add each destination exactly once."""
    other = make_job(company, office_staff)
    outward = make_material_line(job, cost="10", rev="0")
    inward = make_material_line(other, cost="20", rev="0")

    def move_back() -> None:
        inward.cost_set = job.latest_actual
        inward.save()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            outward.cost_set = other.latest_actual
            outward.save()
            pending, worker_pid = start_database_task(pool, move_back)
            await_database_lock(pending, worker_pid)
        pending.result(timeout=10)
    for cost_set, expected in ((job.latest_actual, 20), (other.latest_actual, 10)):
        cost_set.refresh_from_db()
        assert cost_set.summary["cost"] == expected
        assert cost_set.summary_is_current()


def test_migration_rebuilds_invalid_caches_without_altering_quote_evidence(job: Job) -> None:
    """Incremental updates must start from the ledger, not preserve an invalid baseline."""
    line = make_material_line(job, cost="12.34", quantity="1.125", rev="0")
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    executor.migrate([("job", "0010_costline_costline_known_owner")])
    revisions = [{"quote_revision": 1, "summary": {"cost": 123}}]
    try:
        CostSet.objects.filter(pk=line.cost_set_id).update(
            summary={"cost": "invalid", "revisions": revisions}
        )
        CostSet.objects.filter(pk=job.latest_quote_id).update(summary={})
        CostSet.objects.filter(pk=job.latest_estimate_id).update(summary=["invalid"])
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        line.cost_set.refresh_from_db()
        job.latest_quote.refresh_from_db()
        assert line.cost_set.summary["cost"] == 13.8825
        assert line.cost_set.summary["revisions"] == revisions
        assert line.cost_set.summary_is_current()
        assert job.latest_quote.summary == {"cost": 0, "rev": 0, "hours": 0}
        job.latest_estimate.refresh_from_db()
        assert job.latest_estimate.summary == {"cost": 0, "rev": 0, "hours": 0}
        line.refresh_from_db()
        assert line.quantity == Decimal("1.125")
        assert line.unit_cost == Decimal("12.34")
        with pytest.raises(IntegrityError), transaction.atomic():
            CostSet.objects.filter(pk=line.cost_set_id).update(
                summary={"cost": "1", "rev": 0, "hours": 0}
            )
    finally:
        MigrationExecutor(connection).migrate(targets)
