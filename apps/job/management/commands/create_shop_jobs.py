from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.workflow.models import CompanyDefaults


class Command(BaseCommand):
    help = "Create shop jobs for internal purposes"

    def handle(self, *args: object, **kwargs: object) -> None:
        # Define shop job details
        shop_jobs = [
            {
                "name": "Business Development",
                "description": "Sales without a specific company",
            },
            {
                "name": "Bench - busy work",
                "description": (
                    "Busy work not directly tied to company jobs. "
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
        shop_company = company_defaults.shop_company

        created = 0
        updated = 0
        automation_user = Staff.get_automation_user()
        for job_details in shop_jobs:
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Shop jobs ready: {created} created, {updated} updated."
            )
        )
