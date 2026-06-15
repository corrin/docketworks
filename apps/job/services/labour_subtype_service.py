"""Company-level labour-subtype management helpers."""

from decimal import Decimal

from apps.job.models import Job, JobLabourRate, LabourSubtype
from apps.workflow.models import CompanyDefaults


def seed_subtype_onto_existing_jobs(subtype: LabourSubtype) -> int:
    """Create a JobLabourRate for ``subtype`` on every job that lacks one.

    Mirrors the seeding in ``Job.save()``: shop jobs bill no revenue so they get
    ``0.00``; every other job gets the subtype's default rate. This keeps the
    data-integrity invariant — every job has a rate row for every active subtype
    (``data_integrity_service._check_job_business_rules``) — satisfied after a new
    subtype is created, and stops timesheet/estimate entry against the new subtype
    crashing on a missing rate row. Returns the number of rows created.
    """
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
    JobLabourRate.objects.bulk_create(rows, batch_size=1000)
    return len(rows)
