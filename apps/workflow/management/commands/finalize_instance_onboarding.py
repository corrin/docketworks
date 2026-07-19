"""Management command for the post-OAuth instance onboarding workflow."""

from django.core.management.base import BaseCommand, CommandParser

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.services.instance_onboarding import finalize_instance_onboarding


class Command(BaseCommand):
    help = "Finalize Xero onboarding and enable synchronization for a new instance"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--seed-xero",
            action="store_true",
            help="Create missing demo-only Xero configuration and employees",
        )

    def handle(self, *args: object, **options: object) -> None:
        try:
            finalize_instance_onboarding(seed_xero=bool(options["seed_xero"]))
        except AlreadyLoggedException:
            CompanyDefaults.set_xero_sync_enabled(enabled=False)
            raise
        except Exception as exc:
            CompanyDefaults.set_xero_sync_enabled(enabled=False)
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Instance onboarding complete; automated Xero sync is enabled."
            )
        )
