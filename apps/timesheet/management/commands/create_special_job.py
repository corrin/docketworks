"""
Create a special (overhead) job, mirroring the structure of existing ones.

Usage:
    python manage.py create_special_job --name "Last Pay / Bonuses" --dry-run
    python manage.py create_special_job --name "Last Pay / Bonuses"
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.client.models import Client
from apps.job.models import CostSet, Job
from apps.workflow.models import XeroPayItem


class Command(BaseCommand):
    help = "Create a special (overhead) job with quote/estimate/actual cost sets"

    def add_arguments(self, parser):
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

    def handle(self, *args, **options):
        name = options["name"].strip()
        pay_item_name = options["pay_item"].strip()

        # Validate no duplicate
        if Job.objects.filter(name=name).exists():
            raise CommandError(f"Job '{name}' already exists")

        # Resolve client (MSM (Shop) — same as other special jobs)
        try:
            client = Client.objects.get(name="MSM (Shop)")
        except Client.DoesNotExist:
            raise CommandError("Client 'MSM (Shop)' not found")

        # Resolve pay item
        pay_item = XeroPayItem.objects.filter(
            name=pay_item_name, multiplier__isnull=False
        ).first()
        if not pay_item:
            raise CommandError(f"XeroPayItem '{pay_item_name}' not found")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes made:"))
            self.stdout.write(f"  Job: '{name}' (status=special)")
            self.stdout.write(f"  Client: {client.name}")
            self.stdout.write(
                f"  Default pay item: {pay_item.name} ({pay_item.multiplier}x)"
            )
            self.stdout.write("  CostSets: quote, estimate, actual")
            return

        with transaction.atomic():
            job = Job.objects.create(
                name=name,
                status="special",
                client=client,
                contact=None,
                charge_out_rate=0,
                pricing_methodology="time_materials",
                speed_quality_tradeoff="normal",
                job_is_valid=True,
                default_xero_pay_item=pay_item,
            )

            for kind in ("quote", "estimate", "actual"):
                CostSet.objects.create(
                    job=job,
                    kind=kind,
                    rev=1,
                )

        self.stdout.write(
            self.style.SUCCESS(f"Created job '{name}' (id={job.id}) with 3 cost sets.")
        )
