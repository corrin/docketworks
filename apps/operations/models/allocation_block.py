import uuid

from django.db import models

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.operations.models.scheduler_run import SchedulerRun


class AllocationBlock(models.Model):
    """
    A single simulated allocation: one worker, one job, one day, with duration.
    These are the source of truth for the forecast — job projections and day
    summaries are derived from these records.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scheduler_run = models.ForeignKey(
        SchedulerRun,
        on_delete=models.CASCADE,
        related_name="allocation_blocks",
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="allocation_blocks",
    )
    staff = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name="allocation_blocks",
    )
    allocation_date = models.DateField()
    allocated_hours = models.FloatField(
        help_text="Hours allocated to this job for this staff member on this date",
    )
    sequence = models.IntegerField(
        default=0,
        help_text="Ordering within the run for reconstructing the schedule",
    )

    class Meta:
        ordering = ["scheduler_run", "sequence", "allocation_date"]

    def __str__(self) -> str:
        return (
            f"AllocationBlock {self.allocation_date} "
            f"staff={self.staff_id} job={self.job_id} "
            f"{self.allocated_hours}h"
        )
