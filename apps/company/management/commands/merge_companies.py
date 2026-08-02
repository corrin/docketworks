"""Merge duplicate companies that share one name (v1 merge_companies command).

Thin operator front-end over the ONE canonical merge implementation,
``apps.company.services.company_merge_service.merge_companies`` (ADR 0039).
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.services.company_merge_service import merge_companies
from apps.core.models import CompanyDefaults


class Command(BaseCommand):
    """Find same-named duplicate companies and merge them into one primary."""

    help = "Merge duplicate companies with the same name"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register --name (target company name) and --auto (skip confirmation)."""
        parser.add_argument(
            "--name",
            type=str,
            help="Company name to check for duplicates. If not provided, then raise a value error",
        )
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Automatically merge without confirmation",
        )

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002 -- BaseCommand signature
        """Merge every same-named duplicate into the busiest/oldest primary."""
        from apps.job.models import Job  # noqa: PLC0415 -- job imports company at module level

        # Determine which company name to look for
        company_name = options.get("name")

        if not company_name:
            # Use the configured shop company from CompanyDefaults
            company_defaults = CompanyDefaults.get_solo()
            company_name = company_defaults.shop_company.name
        else:
            pass  # explicit company name provided by caller

        self.stdout.write(f"Looking for duplicate companies with name: '{company_name}'")

        # Find all companies with this name. Tombstones are already resolved —
        # they are neither duplicates to fix nor eligible primaries.
        duplicate_companies = Company.objects.filter(
            name=company_name, merged_into__isnull=True
        ).order_by("django_created_at")
        count = duplicate_companies.count()

        if count == 0:
            self.stdout.write(self.style.WARNING(f"No companies found with name '{company_name}'"))
            return
        if count == 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Only one company found with name '{company_name}' - no duplicates to fix"
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {count} companies with name '{company_name}':")
        )

        # Display information about each company
        companies_with_job_counts: list[tuple[Company, int]] = []
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
            response = input("Do you want to merge all duplicates into this company? (yes/no): ")
            if response.lower() != "yes":
                self.stdout.write(self.style.WARNING("Operation cancelled"))
                return

        # Merge duplicates. Same tombstone semantics as the Xero-driven merge
        # (ADR 0034): the loser keeps its row with merged_into set, so any
        # late-arriving reference to it still resolves to the primary.
        for company, _job_count in companies_with_job_counts[1:]:
            self.stdout.write(f"Merging company {company.pk} into {primary_company.pk}...")
            counts = merge_companies(
                company.pk,
                primary_company.pk,
                Staff.get_automation_user(),
            )
            self.stdout.write(f"  Reassigned records: {counts}")

        self.stdout.write(
            self.style.SUCCESS(f"Success! All duplicates merged into company {primary_company.pk}")
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Total jobs now associated with this company: "
                f"{Job.objects.filter(company=primary_company).count()}"
            )
        )
