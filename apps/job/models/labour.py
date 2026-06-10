import uuid
from decimal import Decimal

from django.db import models


class LabourSubtype(models.Model):
    """
    A configurable category of labour (Workshop, Office/Admin, Quoting,
    Delivery, Installation, ...). Every time CostLine belongs to exactly one
    subtype. Subtypes carry the company-level default charge-out rate used to
    seed per-job rates (JobLabourRate) and the is_workshop flag that decides
    whether the subtype counts as workshop work for scheduling and the
    workshop PDF.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    display_order = models.PositiveIntegerField(
        default=0, help_text="Sort order in dropdowns and reports"
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Inactive subtypes keep historical lines valid but are not offered "
            "for new entry and are not seeded onto new jobs"
        ),
    )
    is_workshop = models.BooleanField(
        default=False,
        help_text=(
            "Whether this subtype counts as workshop work for scheduling and "
            "the workshop PDF"
        ),
    )
    default_charge_out_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Company-level rate used to seed JobLabourRate on new jobs",
    )

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name


class JobLabourRate(models.Model):
    """
    The charge-out rate for one labour subtype on one job. Seeded at job
    creation from LabourSubtype.default_charge_out_rate (zero for shop jobs)
    and editable per job afterwards. Replaces the old Job.charge_out_rate.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        "job.Job", on_delete=models.CASCADE, related_name="labour_rates"
    )
    labour_subtype = models.ForeignKey(
        LabourSubtype, on_delete=models.PROTECT, related_name="job_rates"
    )
    charge_out_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "labour_subtype"], name="unique_job_labour_subtype"
            )
        ]

    def __str__(self) -> str:
        return f"{self.job_id} - {self.labour_subtype} @ {self.charge_out_rate}"
