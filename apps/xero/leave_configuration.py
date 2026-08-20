"""Bind fixed Docketworks leave codes to synced Xero payroll items."""

from dataclasses import dataclass

from django.db import transaction

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.timesheet.models import LeaveType
from apps.xero.models import XeroPayItem


@dataclass(frozen=True, slots=True)
class _DefaultMapping:
    """One category's default binding.

    Opus: ``pay_item_name`` is None where Xero pays the category from its own
    calculation — there is no earnings rate or leave type to name. The posting
    surface is not repeated here: it is derived from the code, so this table
    cannot disagree with the classifier about what a category is.
    """

    code: str
    display_name: str
    job_name: str
    pay_item_name: str | None


DEFAULT_MAPPINGS = (
    _DefaultMapping(LeaveType.Code.ANNUAL, "Annual Leave", "Annual Leave", "Annual Leave"),
    _DefaultMapping(LeaveType.Code.SICK, "Sick Leave", "Sick Leave", "Sick Leave"),
    _DefaultMapping(LeaveType.Code.UNPAID, "Unpaid Leave", "Unpaid Leave", "Unpaid Leave"),
    _DefaultMapping(
        LeaveType.Code.BEREAVEMENT,
        "Bereavement Leave",
        "Bereavement Leave",
        "Bereavement Leave",
    ),
    # Opus: No pay item. This bound "Ordinary Time" and so routed public-holiday
    # hours to the Timesheets API — on top of the line Xero computes itself from
    # the employee's working pattern, which is a second payment for the day.
    _DefaultMapping(
        LeaveType.Code.PUBLIC_HOLIDAY,
        "Public Holiday",
        "Statutory holiday",
        None,
    ),
)


@transaction.atomic
def configure_default_leave_types() -> None:
    """Converge the five fixed mappings after shop jobs and Xero items exist."""
    shop_company = CompanyDefaults.get_solo().shop_company
    actor = Staff.get_automation_user()
    for mapping in DEFAULT_MAPPINGS:
        job = Job.objects.get(company=shop_company, name=mapping.job_name, status="special")
        if mapping.pay_item_name is None:
            # Opus: Nothing to bind. The job keeps whatever UI default it has —
            # ``Job.default_xero_pay_item`` is NOT NULL and ``Job.save`` fills it
            # with Ordinary Time — but that default no longer classifies
            # anything: ``LeaveCatalogue`` builds its pay-item index from
            # Leave-API categories only, and time entry on this job resolves no
            # pay item at all, so its lines carry NULL and post nowhere.
            pass
        else:
            pay_item = XeroPayItem.objects.get(name=mapping.pay_item_name, uses_leave_api=True)
            if not pay_item.xero_id:
                raise ValueError(f"Xero payroll item {mapping.pay_item_name} is not linked.")
            if job.default_xero_pay_item_id != pay_item.id:
                job.default_xero_pay_item = pay_item
                job.save(staff=actor, update_fields=["default_xero_pay_item", "updated_at"])
        LeaveType.objects.update_or_create(
            code=mapping.code,
            defaults={"display_name": mapping.display_name, "job": job},
        )
