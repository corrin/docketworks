"""SchedulerRun — one execution of the workshop scheduling algorithm."""

import uuid
from typing import ClassVar

from django.db import models
from django.utils import timezone


class SchedulerRun(models.Model):
    """Records a single run of the workshop scheduling algorithm."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ran_at = models.DateTimeField(default=timezone.now)
    algorithm_version = models.CharField(
        max_length=50,
        default="v1",
        help_text="Version identifier for the scheduling algorithm",
    )
    succeeded = models.BooleanField(default=False)
    failure_reason = models.TextField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        blank=True,
        null=True,
        help_text="Error message if the run failed",
    )
    job_count = models.IntegerField(
        default=0,
        help_text="Number of jobs processed in this run",
    )
    unscheduled_count = models.IntegerField(
        default=0,
        help_text="Number of jobs that could not be scheduled in this run",
    )

    class Meta:
        ordering: ClassVar = ["-ran_at"]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(failure_reason=""), name="failure_reason_not_blank"
            ),
        ]

    def __str__(self) -> str:
        status = "succeeded" if self.succeeded else "failed"
        return f"SchedulerRun {self.ran_at.isoformat()} ({status})"
