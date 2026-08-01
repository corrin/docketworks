import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounting.models.invoice import Invoice
from apps.accounting.services.invoice_calculation import (
    INVOICE_VALID_STATUSES,
    get_job_invoicing_basis,
    get_prior_valid_invoice_total,
)
from apps.accounts.models import Staff
from apps.job.models import Job
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


def get_paid_complete_jobs():
    """Fetches the jobs that are both completed and paid."""
    return (
        Job.objects.filter(status__in=["completed", "recently_completed"], paid=True)
        .select_related("company")
        .order_by("-updated_at")
    )


def archive_complete_jobs(job_ids, staff=None):
    """Archives the jobs on the provided list by changing their statuses"""
    archived_count = 0
    errors = []

    with transaction.atomic():
        for jid in job_ids:
            try:
                job = Job.objects.get(id=jid)
                job.status = "archived"
                job.save(staff=staff)
                archived_count += 1
                logger.info(f"Job {jid} successfully archived")
            except Job.DoesNotExist:
                errors.append(f"Job with id {jid} not found")
            except Exception as e:
                errors.append(f"Failed to archive job {jid}: {str(e)}")
                logger.error(f"Error archiving job {jid}: {str(e)}")

    return errors, archived_count


def get_job_total_value(job: Job) -> Decimal:
    """The total value of a job.

    Invoices are definitive once raised; before that the job is worth whatever
    its pricing basis says. Both figures come from ``invoice_calculation``, so
    this cannot report a value the job could not actually be invoiced for.
    """
    total_invoiced = get_prior_valid_invoice_total(job)
    if total_invoiced > 0:
        return total_invoiced

    return get_job_invoicing_basis(job).target_total


def update_completion_checklist(
    job: Job, updates: dict[str, bool], staff: Staff
) -> Job:
    """Tick or untick front-desk checklist items.

    Job.save() turns each changed field into a job-history event through
    _FIELD_HANDLERS, so there is no audit code here to keep in step. Validation
    of the keys and values belongs to the serializer that accepted them.
    """
    for item, value in updates.items():
        setattr(job, item, value)
    job.save(staff=staff)
    return job


def recalculate_job_invoicing_state(job_id: str, staff) -> None:
    try:
        has_invoices = Invoice.objects.filter(
            job_id=job_id, status__in=INVOICE_VALID_STATUSES
        ).exists()

        if not has_invoices:
            updated = Job.objects.filter(pk=job_id).untracked_update(
                fully_invoiced=False, updated_at=timezone.now()
            )
            if not updated:
                raise Job.DoesNotExist
            return

        job = Job.objects.select_related("latest_actual", "latest_quote").get(pk=job_id)

        # Compared against the same value the job would be invoiced for, so a
        # capped T&M job cannot read "fully invoiced" at one figure while the
        # invoice path uses another.
        job.fully_invoiced = (
            get_prior_valid_invoice_total(job)
            >= get_job_invoicing_basis(job).target_total
        )
        job.save(staff=staff, update_fields=["fully_invoiced", "updated_at"])
    except Job.DoesNotExist:
        logger.error("Provided job id doesn't exist")
        raise
    except Exception as e:
        persist_app_error(e)
        raise


class JobStaffService:
    @staticmethod
    def _touch_job_for_assignment_change(job):
        Job.objects.filter(id=job.id).touch_updated_at(at=timezone.now())

    @staticmethod
    def assign_staff_to_job(job_id, staff_id):
        """Assign a staff member to a job"""
        try:
            job = Job.objects.get(id=job_id)
            staff = Staff.objects.get(id=staff_id)

            if not job.people.filter(id=staff.id).exists():
                job.people.add(staff)
                JobStaffService._touch_job_for_assignment_change(job)

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

            if job.people.filter(id=staff.id).exists():
                job.people.remove(staff)
                JobStaffService._touch_job_for_assignment_change(job)

            return True, None
        except Job.DoesNotExist:
            return False, "Job not found"
        except Staff.DoesNotExist:
            return False, "Staff member not found"
        except Exception as e:
            raise e
