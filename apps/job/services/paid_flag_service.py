"""Paid-flag maintenance for completed jobs.

Marks ``recently_completed`` jobs as paid once every associated invoice is
paid. Beat-scheduled daily via ``apps.job.tasks.set_paid_flag_task``.
"""

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job

logger = logging.getLogger(__name__)


@dataclass
class PaidFlagResult:
    """Result of a paid flag update operation."""

    jobs_updated: int
    unpaid_invoices: int
    missing_invoices: int
    duration_seconds: float
    processed_jobs: list[Job]


def _invoice_counts(job: Job) -> tuple[int, int]:
    """Return (total invoices, unpaid invoices) for a job."""
    invoices = list(job.invoices.all())
    unpaid = sum(1 for invoice in invoices if not invoice.paid)
    return len(invoices), unpaid


def _classify_jobs(
    completed_jobs: list[Job], *, dry_run: bool, verbose: bool
) -> tuple[list[Job], int, int]:
    """Split jobs into fully paid vs. unpaid/uninvoiced; count the latter."""
    jobs_to_update: list[Job] = []
    unpaid_invoices = 0
    missing_invoices = 0

    for job in completed_jobs:
        invoice_count, unpaid_invoice_count = _invoice_counts(job)

        if invoice_count == 0:
            missing_invoices += 1
            if verbose:
                logger.info("Job %s - %s has no associated invoices", job.job_number, job.name)
        elif unpaid_invoice_count > 0:
            unpaid_invoices += unpaid_invoice_count
            if verbose:
                logger.info(
                    "Job %s - %s has %s unpaid invoice(s)",
                    job.job_number,
                    job.name,
                    unpaid_invoice_count,
                )
        else:
            # All invoices are paid
            if verbose:
                logger.info(
                    "Job %s - %s has all invoices paid (%s invoice(s))",
                    job.job_number,
                    job.name,
                    invoice_count,
                )
            if dry_run:
                logger.info("Would mark job %s - %s as paid", job.job_number, job.name)

            jobs_to_update.append(job)

    return jobs_to_update, unpaid_invoices, missing_invoices


def update_paid_flags(*, dry_run: bool = False, verbose: bool = False) -> PaidFlagResult:
    """Update paid flags on completed jobs that have fully paid invoices.

    ``dry_run`` reports without changing anything; ``verbose`` logs per-job
    detail. Returns a PaidFlagResult with operation details.
    """
    start_time = timezone.now()

    completed_jobs = Job.objects.filter(
        status="recently_completed",
        paid=False,
    ).prefetch_related("invoices")

    if verbose:
        logger.info("Found %s completed jobs not marked as paid", completed_jobs.count())

    jobs_to_update, unpaid_invoices, missing_invoices = _classify_jobs(
        list(completed_jobs), dry_run=dry_run, verbose=verbose
    )

    if not dry_run and jobs_to_update:
        automation_user = Staff.get_automation_user()
        with transaction.atomic():
            for job in jobs_to_update:
                job.paid = True
                job.save(staff=automation_user)
                logger.info("Job %s (%s) marked as paid", job.job_number, job.name)

    duration = (timezone.now() - start_time).total_seconds()

    return PaidFlagResult(
        jobs_updated=len(jobs_to_update),
        unpaid_invoices=unpaid_invoices,
        missing_invoices=missing_invoices,
        duration_seconds=duration,
        processed_jobs=jobs_to_update,
    )
