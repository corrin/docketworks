"""Set the paid flag on completed jobs whose invoices are all paid.

The daily beat task (``apps.job.tasks.set_paid_flag_task``) runs the same
service; this command is the operator's on-demand, dry-runnable entry point.
"""

from django.core.management.base import BaseCommand, CommandParser

from apps.job.services.paid_flag_service import update_paid_flags


class Command(BaseCommand):
    """Run the paid-flag service with dry-run and verbose reporting."""

    help = 'Sets the "paid" flag on completed jobs that have paid invoices'

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the dry-run and verbose flags."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making any changes",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Display detailed information about processed jobs",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Delegate to the shared service and report its result."""
        dry_run_option = options["dry_run"]
        verbose_option = options["verbose"]
        if not isinstance(dry_run_option, bool):
            raise TypeError("The dry-run option must be a boolean")
        if not isinstance(verbose_option, bool):
            raise TypeError("The verbose option must be a boolean")

        if dry_run_option:
            self.stdout.write(
                self.style.WARNING("Running in dry-run mode - no changes will be made")
            )

        result = update_paid_flags(dry_run=dry_run_option, verbose=verbose_option)

        if verbose_option:
            verb = "Would mark" if dry_run_option else "Marked"
            for job in result.processed_jobs:
                self.stdout.write(f"{verb} job {job.job_number} - {job.name} as paid")

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Would update' if dry_run_option else 'Successfully updated'} "
                f"{result.jobs_updated} jobs as paid\n"
                f"Jobs with unpaid invoices: {result.unpaid_invoices}\n"
                f"Jobs without invoices: {result.missing_invoices}\n"
                f"Operation completed in {result.duration_seconds:.2f} seconds"
            )
        )
