"""Service for updating paid flags on completed jobs with paid invoices."""

import logging
from dataclasses import dataclass
from typing import List

from django.db import transaction
from django.utils import timezone

from apps.job.models import Job

logger = logging.getLogger(__name__)


@dataclass
class PaidFlagResult:
    """Result of paid flag update operation."""

    jobs_updated: int
    unpaid_invoices: int
    missing_invoices: int
    duration_seconds: float
    processed_jobs: List[Job]


class PaidFlagService:
    """Service for updating paid flags on completed jobs."""

    @staticmethod
    def update_paid_flags(
        dry_run: bool = False, verbose: bool = False
    ) -> PaidFlagResult:
        """
        Update paid flags on completed jobs that have paid invoices.

        Args:
            dry_run: If True, don't make any changes
            verbose: If True, log detailed information

        Returns:
            PaidFlagResult with operation details
        """
        start_time = timezone.now()

        completed_jobs = Job.objects.filter(status="recently_completed", paid=False)

        if verbose:
            logger.info(
                f"Found {completed_jobs.count()} completed jobs not marked as paid"
            )

        jobs_to_update = []
        unpaid_invoices = 0
        missing_invoices = 0

        for job in completed_jobs:
            invoices = job.invoices.all()

            if not invoices.exists():
                missing_invoices += 1
                if verbose:
                    logger.info(
                        f"Job {job.job_number} - {job.name} has no associated invoices"
                    )
                continue

            # Check if all invoices are paid
            paid_invoices = [invoice for invoice in invoices if invoice.paid]
            unpaid_invoice_count = len(invoices) - len(paid_invoices)

            if unpaid_invoice_count > 0:
                unpaid_invoices += unpaid_invoice_count
                if verbose:
                    logger.info(
                        f"Job {job.job_number} - {job.name} has {unpaid_invoice_count} unpaid invoice(s)"
                    )
            else:
                # All invoices are paid
                if verbose:
                    logger.info(
                        f"Job {job.job_number} - {job.name} has all invoices paid "
                        f"({len(paid_invoices)} invoice(s))"
                    )
                if dry_run:
                    logger.info(f"Would mark job {job.job_number} - {job.name} as paid")

                jobs_to_update.append(job)

        if not dry_run and jobs_to_update:
            with transaction.atomic():
                for job in jobs_to_update:
                    job.paid = True
                    job.save()
                    logger.info(f"Job {job.job_number} ({job.name}) marked as paid")

        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()

        return PaidFlagResult(
            jobs_updated=len(jobs_to_update),
            unpaid_invoices=unpaid_invoices,
            missing_invoices=missing_invoices,
            duration_seconds=duration,
            processed_jobs=jobs_to_update,
        )
