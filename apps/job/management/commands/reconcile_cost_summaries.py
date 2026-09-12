"""Check derived cost totals, or explicitly rebuild them from their cost lines."""

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.job.models import CostSet, Job
from apps.job.models.costing import lock_costing_jobs


class Command(BaseCommand):
    """Expose repeatable cache verification and repair without changing the ledger."""

    help = "Check cost summaries; --repair rebuilds incorrect caches from cost lines."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require explicit scope and opt-in for repair."""
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--job", type=int, help="Job number to check or repair")
        scope.add_argument("--all", action="store_true", help="Check or repair all jobs")
        parser.add_argument("--repair", action="store_true", help="Apply cache repairs")

    def handle(self, *_args: object, **options: object) -> None:
        """Visit jobs independently so a repair can be safely restarted."""
        repair = options["repair"]
        job_number = options["job"]
        if not isinstance(repair, bool):
            raise TypeError("The repair option must be a boolean")
        if job_number is not None and not isinstance(job_number, int):
            raise TypeError("The job option must be a job number")
        jobs = Job.objects.order_by("id")
        if job_number is not None:
            jobs = jobs.filter(job_number=job_number)
            if not jobs.exists():
                raise CommandError(f"Job {job_number} does not exist")

        checked = affected = 0
        for job in jobs.only("id", "job_number").iterator(chunk_size=100):
            job_checked, job_affected = self._reconcile_job(job, repair=repair)
            checked += job_checked
            affected += job_affected
        action = "repaired" if repair else "incorrect"
        self.stdout.write(f"Checked {checked} cost sets; {action} {affected}.")
        if affected and not repair:
            raise CommandError(
                "Cost summary check failed; no data changed. Use --repair to rebuild."
            )

    def _reconcile_job(self, job: Job, *, repair: bool) -> tuple[int, int]:
        checked = affected = 0
        with transaction.atomic():
            if repair:
                lock_costing_jobs([job.id])
            cost_sets = CostSet.objects.filter(job=job).only("id", "job_id").order_by("id")
            for cost_set in cost_sets:
                checked += 1
                changed = (
                    cost_set.recalculate_summary() if repair else not cost_set.summary_is_current()
                )
                if changed:
                    affected += 1
                    action = "Repaired" if repair else "Incorrect"
                    self.stdout.write(f"{action} job {job.job_number}, cost set {cost_set.id}")
        return checked, affected
