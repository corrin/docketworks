"""Cached totals follow persisted contributions without rereading their history."""

import re
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models.signals import post_init
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job, make_material_line
from apps.job.models import CostLine, CostSet, Job, LabourSubtype

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["material", "time", "adjust"])
def test_each_cost_kind_tracks_edits_and_deletion(job: Job, kind: str) -> None:
    """Time contributes hours; other kinds must never add their quantities to hours."""
    cost_set = job.latest_estimate
    line = CostLine.objects.create(
        cost_set=cost_set,
        kind=kind,
        desc="Summary contribution",
        quantity=Decimal("1.125"),
        unit_cost=Decimal("12.34"),
        unit_rev=Decimal("20.01"),
        accounting_date=timezone.localdate(),
        labour_subtype=LabourSubtype.default_workshop() if kind == "time" else None,
    )
    hours = Decimal("1.125") if kind == "time" else Decimal("0")
    assert stored_totals(cost_set) == (Decimal("13.88250"), Decimal("22.51125"), hours)
    line.quantity = Decimal("-0.250")
    line.save()
    hours = Decimal("-0.250") if kind == "time" else Decimal("0")
    assert stored_totals(cost_set) == (Decimal("-3.08500"), Decimal("-5.00250"), hours)
    line.delete()
    assert stored_totals(cost_set) == (Decimal("0"), Decimal("0"), Decimal("0"))


@pytest.mark.parametrize("price", ["0", "12.34"])
def test_metadata_and_repeated_saves_do_not_change_totals(job: Job, price: str) -> None:
    """Saving the same row twice must not add its contribution twice."""
    line = make_material_line(job, cost=price, rev=price)
    before = stored_totals(line.cost_set)
    job.refresh_from_db()
    version = job.updated_at
    line.desc = "Changed description"
    line.save(update_fields=["desc"])
    line.save()
    assert stored_totals(line.cost_set) == before
    job.refresh_from_db()
    assert job.updated_at > version


def test_check_and_repair_preserve_ledger_and_archived_revisions(job: Job) -> None:
    """Recovery must repair derived totals without rewriting their evidence."""
    line = make_material_line(job, quantity="1.125", cost="12.34", rev="20.01")
    cost_set = line.cost_set
    revisions = [{"quote_revision": 1, "summary": {"cost": 999}}]
    CostSet.objects.filter(pk=cost_set.id).update(
        summary={"cost": 123, "rev": 456, "hours": 7, "revisions": revisions}
    )
    job.refresh_from_db()
    version = job.updated_at
    before_line = CostLine.objects.values().get(pk=line.id)
    with CaptureQueriesContext(connection) as checked, pytest.raises(CommandError):
        call_command("reconcile_cost_summaries", "--job", str(job.job_number), stdout=StringIO())
    assert not any(re.search(r"\b(UPDATE|INSERT|DELETE)\b", q["sql"], re.I) for q in checked)
    job.refresh_from_db()
    assert job.updated_at == version
    assert not cost_set.summary_is_current()

    call_command(
        "reconcile_cost_summaries", "--job", str(job.job_number), "--repair", stdout=StringIO()
    )
    cost_set.refresh_from_db()
    job.refresh_from_db()
    assert cost_set.summary_is_current()
    assert cost_set.summary["revisions"] == revisions
    assert CostLine.objects.values().get(pk=line.id) == before_line
    assert job.updated_at != version
    version = job.updated_at
    with CaptureQueriesContext(connection) as repaired_again:
        assert cost_set.recalculate_summary() is False
    job.refresh_from_db()
    assert job.updated_at == version
    # The conditional cache UPDATE is allowed; job freshness must stay unchanged.
    assert not any('UPDATE "job_job"' in q["sql"] for q in repaired_again)


def stored_totals(cost_set: CostSet) -> tuple[Decimal, Decimal, Decimal]:
    """Read numeric storage directly so JSON float decoding cannot hide drift."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT (summary->>'cost')::numeric, (summary->>'rev')::numeric, "
            "(summary->>'hours')::numeric FROM job_costset WHERE id = %s",
            [cost_set.id],
        )
        cost, revenue, hours = cursor.fetchone()
    return cost, revenue, hours


def test_moving_a_line_updates_both_cached_totals(
    job: Job, company: Company, office_staff: Staff
) -> None:
    """Refreshing only the destination leaves the source reporting transferred costs."""
    other = make_job(company, office_staff)
    line = make_material_line(job, quantity="1.125", cost="12.34", rev="20.01")
    source = line.cost_set
    line.cost_set = other.latest_actual
    line.save()
    assert stored_totals(source) == (Decimal("0"), Decimal("0"), Decimal("0"))
    assert stored_totals(other.latest_actual) == (
        Decimal("13.88250"),
        Decimal("22.51125"),
        Decimal("0"),
    )


def test_partial_save_uses_persisted_contribution(job: Job) -> None:
    """Unsaved prices on an instance must not affect a quantity-only update."""
    line = make_material_line(job, cost="12.34", rev="20.01")
    line.quantity = Decimal("1.125")
    line.unit_cost = Decimal("999")
    line.save(update_fields=["quantity"])
    assert stored_totals(line.cost_set) == (Decimal("13.88250"), Decimal("22.51125"), Decimal("0"))


def test_operator_time_transfer_rebuilds_both_owners(
    job: Job, company: Company, office_staff: Staff, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bulk time transfers must not leave costs or hours on the source job."""
    from scripts.ops.move_time_between_jobs import main  # noqa: PLC0415

    other = make_job(company, office_staff)
    line = CostLine.objects.create(
        cost_set=job.latest_actual,
        kind="time",
        desc="Transferred time",
        quantity=Decimal("1.125"),
        unit_cost=Decimal("12.34"),
        unit_rev=Decimal("20.01"),
        accounting_date=timezone.localdate(),
        labour_subtype=LabourSubtype.default_workshop(),
        staff=office_staff,
        xero_pay_item=job.default_xero_pay_item,
        meta={"created_from_timesheet": True},
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "move_time_between_jobs",
            "--from",
            str(job.job_number),
            "--to",
            str(other.job_number),
            "--execute",
        ],
    )
    main()
    line.refresh_from_db()
    assert line.cost_set_id == other.latest_actual_id
    assert stored_totals(job.latest_actual) == (Decimal("0"), Decimal("0"), Decimal("0"))
    assert stored_totals(other.latest_actual) == (
        Decimal("13.88250"),
        Decimal("22.51125"),
        Decimal("1.125"),
    )


def test_stale_instance_edit_and_delete_use_current_stored_amounts(job: Job) -> None:
    """Subtracting a stale instance's original value double-counts intervening edits."""
    line = make_material_line(job, cost="10", rev="20")
    stale = CostLine.objects.get(pk=line.id)
    line.quantity = Decimal("2")
    line.save()
    stale.quantity = Decimal("3")
    stale.save(update_fields=["quantity"])
    assert stored_totals(line.cost_set) == (Decimal("30"), Decimal("60"), Decimal("0"))
    line.delete()
    assert stored_totals(stale.cost_set) == (Decimal("0"), Decimal("0"), Decimal("0"))


def test_repeated_fractional_changes_do_not_accumulate_float_error(job: Job) -> None:
    """Repeated additions and removals must leave an exact decimal remainder."""
    retained = make_material_line(job, quantity="0.001", cost="0.01", rev="0.03")
    for _ in range(20):
        temporary = make_material_line(job, quantity="0.333", cost="99999999.99", rev="0")
        temporary.delete()
    assert stored_totals(retained.cost_set) == (
        Decimal("0.00001"),
        Decimal("0.00003"),
        Decimal("0"),
    )


def test_rolled_back_line_change_preserves_cached_totals(job: Job) -> None:
    """A cache updated outside the ledger transaction would survive this rollback."""
    line = make_material_line(job, cost="10", rev="20")
    with transaction.atomic():
        line.quantity = Decimal("5")
        line.save()
        transaction.set_rollback(True)
    line.refresh_from_db()
    assert line.quantity == 1
    assert stored_totals(line.cost_set) == (Decimal("10"), Decimal("20"), Decimal("0"))


@pytest.mark.parametrize("history_size", [0, 1000, 5000])
def test_single_write_does_not_read_cost_history(job: Job, history_size: int) -> None:
    """A full-history rebuild must fail even when its SQL query count stays constant."""
    cost_set = job.latest_actual
    historical = CostLine.objects.bulk_create(
        [
            CostLine(
                cost_set=cost_set,
                kind="material",
                desc="Historical material",
                quantity=Decimal("1"),
                unit_cost=Decimal("1"),
                unit_rev=Decimal("2"),
                accounting_date=timezone.localdate(),
            )
            for _ in range(history_size)
        ]
    )
    if historical:
        cost_set.recalculate_summary()
    loaded: list[CostLine] = []

    def record_instance(instance: CostLine, **_kwargs: object) -> None:
        loaded.append(instance)

    post_init.connect(record_instance, sender=CostLine)
    try:
        with CaptureQueriesContext(connection) as queries:
            make_material_line(job, cost="3", rev="4")
    finally:
        post_init.disconnect(record_instance, sender=CostLine)
    assert len(loaded) <= 4, "A single write materialised historical cost lines"
    assert not any(
        "sum(" in query["sql"].lower() and "job_costline" in query["sql"].lower()
        for query in queries
    ), "A single write aggregated historical cost lines"
    assert stored_totals(cost_set) == (
        Decimal(history_size + 3),
        Decimal(history_size * 2 + 4),
        Decimal("0"),
    )
