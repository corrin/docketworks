from django.core.management.base import BaseCommand

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.workflow.models import CompanyDefaults


class Command(BaseCommand):
    help = "Create shop jobs for internal purposes"

    def handle(self, *args, **kwargs):
        # Define shop job details
        shop_jobs = [
            {
                "name": "Business Development",
                "description": "Sales without a specific client",
            },
            {
                "name": "Bench - busy work",
                "description": (
                    "Busy work not directly tied to client jobs. "
                    "Could slip without significant issues"
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
            {
                "name": "Bereavement Leave",
                "description": "Bereavement leave taken by workers",
            },
            {"name": "Travel", "description": "Travel for work purposes"},
            {
                "name": "Training",
                "description": "Training sessions for upskilling workers",
            },
        ]

        company_defaults = CompanyDefaults.get_solo()
        shop_client = company_defaults.shop_client

        # Iterate through the shop jobs and create them
        automation_user = Staff.get_automation_user()
        for job_details in shop_jobs:
            # Create the job instance
            job = Job(
                name=job_details["name"],
                client=shop_client,
                description="",
                status="special",
                shop_job=True,  # Changed from shop_job to is_shop_job
                job_is_valid=True,
                paid=False,
            )
            job.save(staff=automation_user)

        self.stdout.write(
            self.style.SUCCESS("Shop jobs have been successfully created.")
        )
