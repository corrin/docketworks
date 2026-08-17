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
    code: str
    display_name: str
    job_name: str
    pay_item_name: str
    uses_leave_api: bool


DEFAULT_MAPPINGS = (
    _DefaultMapping(LeaveType.Code.ANNUAL, "Annual Leave", "Annual Leave", "Annual Leave", True),
    _DefaultMapping(LeaveType.Code.SICK, "Sick Leave", "Sick Leave", "Sick Leave", True),
    _DefaultMapping(LeaveType.Code.UNPAID, "Unpaid Leave", "Unpaid Leave", "Unpaid Leave", True),
    _DefaultMapping(
        LeaveType.Code.BEREAVEMENT,
        "Bereavement Leave",
        "Bereavement Leave",
        "Bereavement Leave",
        True,
    ),
    _DefaultMapping(
        LeaveType.Code.PUBLIC_HOLIDAY,
        "Public Holiday",
        "Statutory holiday",
        "Ordinary Time",
        False,
    ),
)


@transaction.atomic
def configure_default_leave_types() -> None:
    """Converge the five fixed mappings after shop jobs and Xero items exist."""
    shop_company = CompanyDefaults.get_solo().shop_company
    actor = Staff.get_automation_user()
    for mapping in DEFAULT_MAPPINGS:
        job = Job.objects.get(company=shop_company, name=mapping.job_name, status="special")
        pay_item = XeroPayItem.objects.get(
            name=mapping.pay_item_name, uses_leave_api=mapping.uses_leave_api
        )
        if not pay_item.xero_id:
            raise ValueError(f"Xero payroll item {mapping.pay_item_name} is not linked.")
        if job.default_xero_pay_item_id != pay_item.id:
            job.default_xero_pay_item = pay_item
            job.save(staff=actor, update_fields=["default_xero_pay_item", "updated_at"])
        LeaveType.objects.update_or_create(
            code=mapping.code,
            defaults={"display_name": mapping.display_name, "job": job},
        )
