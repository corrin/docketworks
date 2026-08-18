"""Reference data the timesheet entry UI needs: selectable staff and jobs.

Query construction belongs here so the API router remains a thin transport
boundary.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.accounts.services.payroll_terms import salary_cost_rate, salary_term_on
from apps.accounts.staff_directory import get_displayable_staff
from apps.job.models import Job
from apps.job.services import job_search
from apps.job.services.job_service import JobLabourRateData, job_labour_rate_data

logger = logging.getLogger(__name__)

# Jobs selectable for time entry. Fixed-price jobs can safely receive late time
# entries after archival (the invoice total isn't affected), so allow a
# short window after archival for post-pickup adjustments.
ACTIVE_JOB_STATUSES = (
    "draft",
    "awaiting_approval",
    "approved",
    "in_progress",
    "unusual",
    "recently_completed",
    "special",
)
ARCHIVED_FIXED_PRICE_WINDOW = timedelta(days=7)


class TimesheetStaffData(TypedDict):
    """Data contract for TimesheetStaffData."""

    id: str
    name: str
    firstName: str
    lastName: str
    office_email: str
    icon_url: str | None
    wageRate: Decimal
    pay_basis: str | None


class TimesheetStaffListData(TypedDict):
    """Data contract for TimesheetStaffListData."""

    staff: list[TimesheetStaffData]
    total_count: int


class TimesheetJobData(TypedDict):
    """Data contract for TimesheetJobData."""

    id: UUID
    job_number: int
    name: str
    company_name: str | None
    status: str
    labour_rates: list[JobLabourRateData]
    has_actual_costset: bool
    leave_type: str | None
    estimated_hours: float | None
    default_xero_pay_item_id: UUID | None
    default_xero_pay_item_name: str | None
    shop_job: bool
    is_urgent: bool


class TimesheetJobListData(TypedDict):
    """Data contract for TimesheetJobListData."""

    jobs: list[TimesheetJobData]
    total_count: int


def get_staff_for_date(target_date: date) -> TimesheetStaffListData:
    """Staff selectable for time entry on a date.

    Populate the ``icon_url`` key declared by the generated-client contract.
    """
    staff_data: list[TimesheetStaffData] = [
        {
            "id": str(member.id),
            "name": member.get_display_name(),
            "firstName": member.first_name,
            "lastName": member.last_name,
            "office_email": member.office_email,
            "icon_url": member.icon.url if member.icon else None,
            "wageRate": (
                salary_cost_rate(salary_term_on(member, target_date))
                if member.pay_basis == "salary"
                else member.wage_rate
            ),
            "pay_basis": member.pay_basis,
        }
        for member in get_displayable_staff(target_date=target_date)
    ]
    return {"staff": staff_data, "total_count": len(staff_data)}


def _job_data(job: Job) -> TimesheetJobData:
    """Shape one job for the timesheet job picker."""
    estimate = job.get_latest("estimate")
    pay_item = job.default_xero_pay_item
    return {
        "id": job.id,
        "job_number": job.job_number,
        "name": job.name,
        "company_name": job.company.name if job.company else None,
        "status": job.status,
        "labour_rates": [job_labour_rate_data(rate) for rate in job.labour_rates.all()],
        "has_actual_costset": job.get_latest("actual") is not None,
        # A job whose default pay item posts through Xero's Leave API is a leave
        # job; its pay item name is the leave type.
        "leave_type": pay_item.name if pay_item else None,
        "estimated_hours": estimate.summary.get("hours") if estimate else None,
        "default_xero_pay_item_id": pay_item.id if pay_item else None,
        "default_xero_pay_item_name": pay_item.name if pay_item else None,
        "shop_job": job.shop_job,
        "is_urgent": job.is_urgent,
    }


def _entry_job_queryset() -> QuerySet[Job]:
    """Load the relations _job_data reads, once rather than per row."""
    return Job.objects.select_related(
        "company", "default_xero_pay_item", "latest_actual", "latest_estimate"
    ).prefetch_related("labour_rates__labour_subtype")


def get_jobs_for_entry(search: str = "") -> TimesheetJobListData:
    """Jobs available for time entry.

    With `search`, searches the WHOLE table instead of the active set — the
    picker already holds the active set and asks for this only to reach what it
    excludes, which in practice is archived jobs.
    """
    if search:
        jobs = job_search.search_jobs(_entry_job_queryset(), search)
    else:
        recent_cutoff = timezone.now() - ARCHIVED_FIXED_PRICE_WINDOW
        jobs = (
            _entry_job_queryset()
            .filter(
                Q(status__in=ACTIVE_JOB_STATUSES)
                | Q(
                    status="archived",
                    pricing_methodology="fixed_price",
                    completed_at__gte=recent_cutoff,
                )
            )
            .order_by("job_number")
        )
    job_data = [_job_data(job) for job in jobs]
    return {"jobs": job_data, "total_count": len(job_data)}
