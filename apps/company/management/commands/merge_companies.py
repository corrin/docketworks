from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.services.company_merge_service import reassign_company_fk_records
from apps.job.models import Job
from apps.workflow.models import CompanyDefaults


class Command(BaseCommand):
    help = "Merge duplicate companies with the same name"

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            type=str,
            help="Company name to check for duplicates. If not provided, "
            "then raise a value error",
        )
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Automatically merge without confirmation",
        )

    def handle(self, *args, **options):
        # Determine which company name to look for
        company_name = options.get("name")

        if not company_name:
            # Use the configured shop company from CompanyDefaults
            company_defaults = CompanyDefaults.get_solo()
            company_name = company_defaults.shop_company.name
        else:
            pass  # explicit company name provided by caller

        self.stdout.write(
            f"Looking for duplicate companies with name: '{company_name}'"
        )

        # Find all companies with this name
        duplicate_companies = Company.objects.filter(name=company_name).order_by(
            "django_created_at"
        )
        count = duplicate_companies.count()

        if count == 0:
            self.stdout.write(
                self.style.WARNING(f"No companies found with name '{company_name}'")
            )
            return
        elif count == 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Only one company found with name '{company_name}' - "
                    f"no duplicates to fix"
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {count} companies with name '{company_name}':")
        )

        # Display information about each company
        companies_with_job_counts = []
        for i, company in enumerate(duplicate_companies):
            job_count = Job.objects.filter(company=company).count()
            companies_with_job_counts.append((company, job_count))

            self.stdout.write(f"{i + 1}. Company ID: {company.pk}")
            self.stdout.write(f"   Created: {company.django_created_at}")
            self.stdout.write(f"   Jobs: {job_count}")
            if company.xero_contact_id:
                self.stdout.write(f"   Xero Contact ID: {company.xero_contact_id}")

        # Sort by job count (descending) and then by creation date (ascending)
        companies_with_job_counts.sort(key=lambda x: (-x[1], x[0].django_created_at))

        primary_company = companies_with_job_counts[0][0]
        self.stdout.write(
            self.style.SUCCESS(
                f"Recommended primary company: {primary_company.pk} "
                f"(has {companies_with_job_counts[0][1]} jobs)"
            )
        )

        # Ask for confirmation unless --auto flag is used
        if not options["auto"]:
            response = input(
                "Do you want to merge all duplicates into this company? (yes/no): "
            )
            if response.lower() != "yes":
                self.stdout.write(self.style.WARNING("Operation cancelled"))
                return

        # Merge duplicates
        with transaction.atomic():
            for company, job_count in companies_with_job_counts[1:]:
                self.stdout.write(
                    f"Merging company {company.pk} into {primary_company.pk}..."
                )

                # Reassign every company-FK record (Jobs, Invoices, Bills,
                # Credit Notes, Quotes, POs, supplier references). The prior
                # implementation only moved Jobs; the others ended up orphaned
                # on the deleted company via the PROTECT constraint failure
                # path — or silently lost on cascade with the old pointer.
                counts = reassign_company_fk_records(
                    company,
                    primary_company,
                    Staff.get_automation_user(),
                    logger_prefix="[manual-merge] ",
                )
                self.stdout.write(f"  Reassigned records: {counts}")

                # Delete the duplicate company — safe now that every PROTECTed
                # FK has been moved onto the primary.
                company.delete()
                self.stdout.write(f"  Deleted duplicate company {company.pk}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Success! All duplicates merged into company {primary_company.pk}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Total jobs now associated with this company: "
                f"{Job.objects.filter(company=primary_company).count()}"
            )
        )
