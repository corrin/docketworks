import signal
import sys

from django.apps import apps
from django.core.management.base import BaseCommand

from apps.workflow.scheduler import get_scheduler


class Command(BaseCommand):
    help = "Start the shared APScheduler loop (runs forever)."

    def handle(self, *args, **options):
        # Register jobs from each app that has them
        workflow_app = apps.get_app_config("workflow")
        workflow_app._register_xero_jobs()

        quoting_app = apps.get_app_config("quoting")
        quoting_app._register_scraper_jobs()

        job_app = apps.get_app_config("job")
        job_app._register_job_jobs()

        operations_app = apps.get_app_config("operations")
        operations_app._register_operations_jobs()

        try:
            scheduler = get_scheduler()
            scheduler.start()
            self.stdout.write(
                self.style.SUCCESS("APScheduler started. Waiting for jobs…")
            )
            signal.pause()  # keep the process alive until SIGTERM/SIGINT
        except Exception as e:
            self.stderr.write(f"Failed to start scheduler: {e}")
            sys.exit(1)
