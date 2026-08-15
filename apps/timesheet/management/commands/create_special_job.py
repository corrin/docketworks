"""Create a special (overhead) job, mirroring the structure of existing ones.

Usage:
    python manage.py create_special_job --name "Last Pay / Bonuses" --dry-run
    python manage.py create_special_job --name "Last Pay / Bonuses"
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models import Job

from ._repair_shared import get_earnings_pay_item_by_name


class Command(BaseCommand):
    """Create one special-status job on the shop company."""

    help = "Create a special (overhead) job with quote/estimate/actual cost sets"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the job name, pay-item override, and dry-run flag."""
        parser.add_argument(
            "--name",
            type=str,
            required=True,
            help="Name of the special job to create",
        )
        parser.add_argument(
            "--pay-item",
            type=str,
            default="Ordinary Time",
            help="Default Xero pay item name (default: Ordinary Time)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing to DB",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Validate the inputs, then create the job (or report the dry run)."""
        name_option = options.get("name")
        if not isinstance(name_option, str):
            raise TypeError("The name option must be a string")
        pay_item_option = options.get("pay_item")
        if not isinstance(pay_item_option, str):
            raise TypeError("The pay-item option must be a string")
        dry_run = options.get("dry_run")
        if not isinstance(dry_run, bool):
            raise TypeError("The dry-run option must be a boolean")

        name = name_option.strip()
        if not name:
            raise CommandError("The job name must not be blank")
        if Job.objects.filter(name=name).exists():
            raise CommandError(f"Job '{name}' already exists")

        company = CompanyDefaults.get_solo().shop_company
        pay_item = get_earnings_pay_item_by_name(pay_item_option.strip())

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes made:"))
            self.stdout.write(f"  Job: '{name}' (status=special)")
            self.stdout.write(f"  Company: {company.name}")
            self.stdout.write(f"  Default pay item: {pay_item.name} ({pay_item.multiplier}x)")
            self.stdout.write("  CostSets: quote, estimate, actual")
            return

        with transaction.atomic():
            job = Job(
                name=name,
                status="special",
                company=company,
                pricing_methodology="time_materials",
                speed_quality_tradeoff="normal",
                job_is_valid=True,
                default_xero_pay_item_id=pay_item.id,
            )
            # v1 created the three CostSets by hand after this save; v2's
            # Job.save() creates the estimate/quote/actual rev-1 sets itself,
            # so creating them again would violate unique_job_kind_rev.
            job.save(staff=Staff.get_automation_user())

        self.stdout.write(
            self.style.SUCCESS(f"Created job '{name}' (id={job.id}) with 3 cost sets.")
        )
