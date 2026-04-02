import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounting.enums import InvoiceStatus
from apps.accounting.models.invoice import Invoice
from apps.accounts.models import Staff
from apps.job.models import Job
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger(__name__)


def get_paid_complete_jobs():
    """Fetches the jobs that are both completed and paid."""
    return (
        Job.objects.filter(status__in=["completed", "recently_completed"], paid=True)
        .select_related("client")
        .order_by("-updated_at")
    )


def archive_complete_jobs(job_ids):
    """Archives the jobs on the provided list by changing their statuses"""
    archived_count = 0
    errors = []

    with transaction.atomic():
        for jid in job_ids:
            try:
                job = Job.objects.get(id=jid)
                job.status = "archived"
                job.save(update_fields=["status", "updated_at"])
                archived_count += 1
                logger.info(f"Job {jid} successfully archived")
            except Job.DoesNotExist:
                errors.append(f"Job with id {jid} not found")
            except Exception as e:
                errors.append(f"Failed to archive job {jid}: {str(e)}")
                logger.error(f"Error archiving job {jid}: {str(e)}")

    return errors, archived_count


def get_job_total_value(job: Job) -> Decimal:
    """
    Get the total value of a job using the definitive logic:
    1. If invoiced: Use total invoice amount (definitive)
    2. Else if quote job: Use quote revenue
    3. Else (T&M): Use actual revenue

    Args:
        job: Job instance

    Returns:
        Decimal: Total job value
    """
    # Check for invoices first - they override everything
    INVOICE_VALID_STATUSES = [
        status
        for (status, _) in InvoiceStatus.choices
        if status not in ["VOIDED", "DELETED"]
    ]

    total_invoiced = Decimal(
        Invoice.objects.filter(
            job_id=job.id, status__in=INVOICE_VALID_STATUSES
        ).aggregate(total=Coalesce(Sum("total_excl_tax"), Decimal("0")))["total"]
    )

    if total_invoiced > 0:
        return total_invoiced

    # No invoices - check pricing methodology
    if job.pricing_methodology == "fixed_price":
        quote = job.get_latest("quote")
        if quote and quote.summary:
            return Decimal(str(quote.summary.get("rev", 0)))
        return Decimal("0.00")
    else:
        # T&M job - use actual
        actual = job.get_latest("actual")
        if actual and actual.summary:
            return Decimal(str(actual.summary.get("rev", 0)))
        return Decimal("0.00")


def recalculate_job_invoicing_state(job_id: str) -> None:
    try:
        INVOICE_VALID_STATUSES = [
            status
            for (status, _) in InvoiceStatus.choices
            if status not in ["VOIDED", "DELETED"]
        ]

        has_invoices = Invoice.objects.filter(
            job_id=job_id, status__in=INVOICE_VALID_STATUSES
        ).exists()

        if not has_invoices:
            updated = Job.objects.filter(pk=job_id).update(
                fully_invoiced=False, updated_at=timezone.now()
            )
            if not updated:
                raise Job.DoesNotExist
            return

        job = Job.objects.select_related("latest_actual", "latest_quote").get(pk=job_id)

        total_invoiced = Decimal(
            Invoice.objects.filter(
                job_id=job_id, status__in=INVOICE_VALID_STATUSES
            ).aggregate(total=Coalesce(Sum("total_excl_tax"), Decimal("0")))["total"]
        )

        # Fixed-price jobs compare against quote; T&M against actuals
        if job.pricing_methodology == "fixed_price" and job.latest_quote:
            target_amount = Decimal(str(job.latest_quote.total_revenue))
        else:
            target_amount = Decimal(str(job.latest_actual.total_revenue))

        job.fully_invoiced = total_invoiced >= target_amount
        job.save(update_fields=["fully_invoiced", "updated_at"])
    except Job.DoesNotExist:
        logger.error("Provided job id doesn't exist")
        raise
    except Exception as e:
        try:
            persist_and_raise(e)
        except AlreadyLoggedException:
            raise


class JobStaffService:
    @staticmethod
    def assign_staff_to_job(job_id, staff_id):
        """Assign a staff member to a job"""
        try:
            job = Job.objects.get(id=job_id)
            staff = Staff.objects.get(id=staff_id)

            if staff not in job.people.all():
                job.people.add(staff)

            return True, None
        except Job.DoesNotExist:
            return False, "Job not found"
        except Staff.DoesNotExist:
            return False, "Staff member not found"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def remove_staff_from_job(job_id, staff_id):
        """Remove a staff member from a job"""
        try:
            job = Job.objects.get(id=job_id)
            staff = Staff.objects.get(id=staff_id)

            if staff in job.people.all():
                job.people.remove(staff)

            return True, None
        except Job.DoesNotExist:
            return False, "Job not found"
        except Staff.DoesNotExist:
            return False, "Staff member not found"
        except Exception as e:
            raise e
