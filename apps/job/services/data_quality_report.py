"""Service for archived jobs compliance data quality check."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from django.utils import timezone

from apps.job.models import Job
from apps.job.services.job_service import get_job_total_value


class ArchivedJobsComplianceService:
    """Service to check that all archived jobs are compliant."""

    def get_compliance_report(self) -> Dict[str, Any]:
        """
        Generate compliance report for archived jobs.

        Returns:
            Dict with specific structure for archived jobs compliance.
        """
        # Get all archived jobs, excluding rejected ones
        archived_jobs = Job.objects.filter(status="archived", rejected_flag=False)
        total_archived = archived_jobs.count()

        # Find non-compliant jobs with detailed categorization
        non_compliant_list = []

        # Summary counters
        not_invoiced_count = 0
        not_paid_count = 0
        not_cancelled_count = 0
        has_open_tasks_count = 0

        for job in archived_jobs.select_related("client"):
            issues = []

            # Job should either be cancelled/rejected OR (fully invoiced AND paid)
            if not job.rejected_flag and not (job.fully_invoiced and job.paid):
                # Determine specific issues
                if not job.rejected_flag and not job.fully_invoiced:
                    issues.append("Not invoiced")
                    not_invoiced_count += 1
                elif job.fully_invoiced and not job.paid:
                    issues.append("Not paid")
                    not_paid_count += 1

                # Check for open tasks (you may need to adjust this based on your task model)
                # For now, we'll check if the job should have been cancelled
                if not job.rejected_flag and not job.fully_invoiced and not job.paid:
                    not_cancelled_count += 1
                    if "Not invoiced" not in issues:
                        issues.append("Not cancelled")

                # Add to non-compliant list if there are issues
                if issues:
                    # Get job value using the reusable service method and round to 2 decimal places
                    job_value = get_job_total_value(job).quantize(Decimal("0.01"))

                    for issue in issues:
                        non_compliant_list.append(
                            {
                                "job_id": str(job.id),
                                "job_number": job.job_number,
                                "client_name": (
                                    job.client.name if job.client else "Shop Job"
                                ),
                                "archived_date": (
                                    timezone.localtime(job.updated_at).date()
                                    if job.updated_at
                                    else None
                                ),
                                "current_status": job.status,
                                "issue": issue,
                                "invoice_status": self._get_invoice_status(job),
                                "outstanding_amount": (
                                    self._get_outstanding_amount(job)
                                    if issue == "Not paid"
                                    else None
                                ),
                                "job_value": job_value,
                                "price_cap": job.price_cap,
                            }
                        )

        return {
            "total_archived_jobs": total_archived,
            "non_compliant_jobs": non_compliant_list,
            "summary": {
                "not_invoiced": not_invoiced_count,
                "not_paid": not_paid_count,
                "not_cancelled": not_cancelled_count,
                "has_open_tasks": has_open_tasks_count,  # Will be 0 for now
            },
            "checked_at": datetime.now(),
        }

    def _get_invoice_status(self, job: Job) -> Optional[str]:
        """Determine invoice status for a job."""
        if not job.fully_invoiced:
            return None
        elif job.paid:
            return "Paid"
        else:
            return "Sent"

    def _get_outstanding_amount(self, job: Job) -> Optional[Decimal]:
        """Get outstanding amount for unpaid invoiced jobs."""
        # This would need to be calculated from your invoice/payment models
        # For now, returning a placeholder
        if job.fully_invoiced and not job.paid:
            # You'd calculate this from actual invoice data
            return Decimal("0.00")
        return None
