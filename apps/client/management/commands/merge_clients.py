from django.core.management.base import BaseCommand
from django.db import transaction

from apps.client.models import Client
from apps.job.models import Job
from apps.workflow.models import CompanyDefaults


class Command(BaseCommand):
    help = "Merge duplicate clients with the same name"

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            type=str,
            help="Client name to check for duplicates. If not provided, "
            "then raise a value error",
        )
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Automatically merge without confirmation",
        )

    def handle(self, *args, **options):
        # Determine which client name to look for
        client_name = options.get("name")

        if not client_name:
            # Use shop client name from CompanyDefaults
            company_defaults = CompanyDefaults.get_solo()
            if not company_defaults:
                self.stdout.write(self.style.ERROR("CompanyDefaults not found"))
                return

            client_name = company_defaults.shop_client_name
            if not client_name:
                self.stdout.write(
                    self.style.ERROR(
                        "shop_client_name not configured in CompanyDefaults"
                    )
                )
                return

        self.stdout.write(f"Looking for duplicate clients with name: '{client_name}'")

        # Find all clients with this name
        duplicate_clients = Client.objects.filter(name=client_name).order_by(
            "django_created_at"
        )
        count = duplicate_clients.count()

        if count == 0:
            self.stdout.write(
                self.style.WARNING(f"No clients found with name '{client_name}'")
            )
            return
        elif count == 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Only one client found with name '{client_name}' - "
                    f"no duplicates to fix"
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {count} clients with name '{client_name}':")
        )

        # Display information about each client
        clients_with_job_counts = []
        for i, client in enumerate(duplicate_clients):
            job_count = Job.objects.filter(client=client).count()
            clients_with_job_counts.append((client, job_count))

            self.stdout.write(f"{i + 1}. Client ID: {client.pk}")
            self.stdout.write(f"   Created: {client.django_created_at}")
            self.stdout.write(f"   Jobs: {job_count}")
            if client.xero_contact_id:
                self.stdout.write(f"   Xero Contact ID: {client.xero_contact_id}")

        # Sort by job count (descending) and then by creation date (ascending)
        clients_with_job_counts.sort(key=lambda x: (-x[1], x[0].django_created_at))

        primary_client = clients_with_job_counts[0][0]
        self.stdout.write(
            self.style.SUCCESS(
                f"Recommended primary client: {primary_client.pk} "
                f"(has {clients_with_job_counts[0][1]} jobs)"
            )
        )

        # Ask for confirmation unless --auto flag is used
        if not options["auto"]:
            response = input(
                "Do you want to merge all duplicates into this client? (yes/no): "
            )
            if response.lower() != "yes":
                self.stdout.write(self.style.WARNING("Operation cancelled"))
                return

        # Merge duplicates
        with transaction.atomic():
            for client, job_count in clients_with_job_counts[1:]:
                self.stdout.write(
                    f"Merging client {client.pk} into {primary_client.pk}..."
                )

                # Update all jobs to point to the primary client
                jobs_updated = Job.objects.filter(client=client).update(
                    client=primary_client
                )
                self.stdout.write(f"  Updated {jobs_updated} jobs")

                # Delete the duplicate client
                client.delete()
                self.stdout.write(f"  Deleted duplicate client {client.pk}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Success! All duplicates merged into client {primary_client.pk}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Total jobs now associated with this client: "
                f"{Job.objects.filter(client=primary_client).count()}"
            )
        )
