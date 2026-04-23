import uuid

from django.db import models

from apps.job.models import Job
from apps.operations.models.scheduler_run import SchedulerRun


class UnscheduledReason(models.TextChoices):
    MISSING_ESTIMATE_OR_QUOTE_HOURS = (
        "missing_estimate_or_quote_hours",
        "Missing estimate or quote hours",
    )
    MIN_PEOPLE_EXCEEDS_STAFF = (
        "min_people_exceeds_staff",
        "min_people exceeds available workshop staff",
    )
    INVALID_STAFFING_CONSTRAINTS = (
        "invalid_staffing_constraints",
        "Invalid staffing constraints (max_people < min_people)",
    )


class JobProjection(models.Model):
    """
    Forecast output for a single job within a scheduler run.
    Only created for successfully scheduled jobs; unschedulable jobs are
    recorded via the unscheduled_reason fields instead.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scheduler_run = models.ForeignKey(
        SchedulerRun,
        on_delete=models.CASCADE,
        related_name="job_projections",
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="projections",
    )
    anticipated_start_date = models.DateField(null=True, blank=True)
    anticipated_end_date = models.DateField(null=True, blank=True)
    remaining_hours = models.FloatField(
        help_text="Remaining hours at the time of this scheduler run",
    )
    is_late = models.BooleanField(default=False)
    # Unscheduled fields (populated when the job cannot be scheduled)
    is_unscheduled = models.BooleanField(default=False)
    unscheduled_reason = models.CharField(
        max_length=50,
        choices=UnscheduledReason.choices,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["scheduler_run", "job__priority"]
        unique_together = [("scheduler_run", "job")]

    def __str__(self) -> str:
        return f"JobProjection job={self.job_id} run={self.scheduler_run_id}"
