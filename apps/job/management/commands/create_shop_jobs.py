"""Create (or refresh) the twelve internal shop jobs.

The E2E timesheet specs and ``finalize_instance_onboarding`` both find these
jobs by exact name, so the names are a contract — "Annual Leave" in
particular is looked up verbatim.
"""

from typing import TypedDict

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models import Job


class _ShopJobSpec(TypedDict):
    """Name/description pair for one internal shop job."""

    name: str
    description: str


#: The one shop job the code needs to find again: every break is booked to
#: it. It is found through ``CompanyDefaults.break_job``, which this command
#: sets; the name is only how the command recognises its own job.
BREAK_JOB_NAME = "Break"

SHOP_JOBS: tuple[_ShopJobSpec, ...] = (
    {
        "name": "Business Development",
        "description": "Sales without a specific company",
    },
    {
        "name": "Bench - busy work",
        "description": (
            "Busy work not directly tied to company jobs. Could slip without significant issues"
        ),
    },
    {
        "name": "Worker Admin",
        "description": (
            "Mask fittings, meetings, or other worker-related admin. "
            "Unlike bench, this cannot slip much"
        ),
    },
    {
        "name": "Office Admin",
        "description": "General office administration tasks",
    },
    {"name": "Annual Leave", "description": "Annual leave taken by workers"},
    {"name": "Sick Leave", "description": "Sick leave taken by workers"},
    {"name": "Unpaid Leave", "description": "Unpaid leave taken by workers"},
    {
        "name": "Bereavement Leave",
        "description": "Bereavement leave taken by workers",
    },
    {
        "name": "Statutory holiday",
        "description": "Paid statutory holidays and office closure days",
    },
    {
        "name": BREAK_JOB_NAME,
        "description": "Breaks: paid breaks and lunch, which no customer is billed for",
    },
    {"name": "Travel", "description": "Travel for work purposes"},
    {
        "name": "Training",
        "description": "Training sessions for upskilling workers",
    },
)


class Command(BaseCommand):
    """Create or update the shop jobs on the shop company."""

    help = "Create shop jobs for internal purposes"

    def handle(self, *_args: object, **_options: object) -> None:
        """Upsert each shop job by (name, shop company); refuse on ambiguity."""
        company_defaults = CompanyDefaults.get_solo()
        shop_company = company_defaults.shop_company

        created = 0
        updated = 0
        automation_user = Staff.get_automation_user()
        for job_details in SHOP_JOBS:
            matches = Job.objects.filter(
                name=job_details["name"],
                company=shop_company,
            )
            if matches.count() > 1:
                raise CommandError(
                    f"Multiple shop jobs named '{job_details['name']}' already exist."
                )
            job = matches.first()
            if job is None:
                job = Job(name=job_details["name"], company=shop_company)
                created += 1
            else:
                updated += 1
            job.description = job_details["description"]
            job.status = "special"
            job.job_is_valid = True
            job.paid = False
            job.save(staff=automation_user)
            if job.name == BREAK_JOB_NAME:
                company_defaults.break_job = job
                company_defaults.save(update_fields=["break_job"])

        self.stdout.write(
            self.style.SUCCESS(f"Shop jobs ready: {created} created, {updated} updated.")
        )
