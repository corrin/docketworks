"""Company-level labour-subtype management helpers."""

from decimal import Decimal

from django.db import connection, transaction

from apps.job.models import Job, JobLabourRate, LabourSubtype
from apps.workflow.models import CompanyDefaults


def seed_subtype_onto_existing_jobs(subtype: LabourSubtype) -> int:
    """Create a JobLabourRate for ``subtype`` on every job that lacks one.

    Mirrors the seeding in ``Job.save()``: shop jobs bill no revenue so they get
    ``0.00``; every other job gets the subtype's default rate. This keeps the
    data-integrity invariant — every job has a rate row for every active subtype
    (``data_integrity_service._check_job_business_rules``) — satisfied after a new
    subtype is created, and stops timesheet/estimate entry against the new subtype
    crashing on a missing rate row. Returns the number of missing rows attempted;
    benign duplicate insert races are ignored and followed by an invariant check.
    """
    if not subtype.is_active:
        raise ValueError(
            f"Cannot seed inactive LabourSubtype '{subtype.name}' onto jobs."
        )

    with transaction.atomic():
        table_name = connection.ops.quote_name(Job._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {table_name} IN SHARE ROW EXCLUSIVE MODE")

        shop_client_id = CompanyDefaults.get_solo().shop_client_id
        existing_job_ids = set(
            JobLabourRate.objects.filter(labour_subtype=subtype).values_list(
                "job_id", flat=True
            )
        )
        rows = [
            JobLabourRate(
                job_id=job_id,
                labour_subtype=subtype,
                charge_out_rate=(
                    Decimal("0.00")
                    if client_id == shop_client_id
                    else subtype.default_charge_out_rate
                ),
            )
            for job_id, client_id in Job.objects.exclude(
                id__in=existing_job_ids
            ).values_list("id", "client_id")
        ]
        JobLabourRate.objects.bulk_create(rows, batch_size=1000, ignore_conflicts=True)
        missing_job_ids = list(
            Job.objects.exclude(labour_rates__labour_subtype=subtype).values_list(
                "id", flat=True
            )[:10]
        )
        if missing_job_ids:
            raise RuntimeError(
                "Failed to satisfy active labour-subtype rate-row invariant "
                f"for subtype '{subtype.name}'. Missing example job ids: "
                f"{missing_job_ids}"
            )
        return len(rows)
