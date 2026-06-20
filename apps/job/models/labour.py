import uuid
from decimal import Decimal

from django.db import models


class LabourSubtype(models.Model):
    """
    A configurable category of labour (Workshop, Admin, Quoting, Onsite,
    Supervision, ...). Every time CostLine belongs to exactly one
    subtype. Subtypes carry the company-level default charge-out rate used to
    seed per-job rates (JobLabourRate). The is_workshop flag identifies the
    default workshop subtype; counts_for_scheduling identifies labour that
    consumes the workshop staff pool.
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
            "Whether this subtype is the default workshop subtype for staff "
            "and rate selection"
        ),
    )
    counts_for_scheduling = models.BooleanField(
        default=False,
        help_text=(
            "Whether this labour consumes the production staff pool for "
            "scheduling and workshop PDF remaining-hours calculations"
        ),
    )
    default_charge_out_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Company-level rate used to seed JobLabourRate on new jobs",
    )

    class Meta:
        ordering = ["display_order", "name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(default_charge_out_rate__gte=0),
                name="laboursubtype_default_rate_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def default_workshop(cls) -> "LabourSubtype":
        """The first active workshop subtype by display order."""
        subtype = (
            cls.objects.filter(is_active=True, is_workshop=True)
            .order_by("display_order")
            .first()
        )
        if subtype is None:
            raise ValueError("No active workshop LabourSubtype configured.")
        return subtype

    @classmethod
    def default_non_workshop(cls) -> "LabourSubtype":
        """The default active non-workshop subtype for office/admin time."""
        subtype = cls.objects.filter(
            name="Admin", is_active=True, is_workshop=False
        ).first()
        if subtype is not None:
            return subtype

        subtype = (
            cls.objects.filter(is_active=True, is_workshop=False)
            .order_by("display_order")
            .first()
        )
        if subtype is None:
            raise ValueError("No active non-workshop LabourSubtype configured.")
        return subtype


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
        # Stable API ordering: frontend dropdowns and the workshop-rate helper
        # rely on labour_rates arriving in subtype display order.
        ordering = ["labour_subtype__display_order", "labour_subtype__name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(charge_out_rate__gte=0),
                name="joblabourrate_charge_out_rate_non_negative",
            ),
            models.UniqueConstraint(
                fields=["job", "labour_subtype"], name="unique_job_labour_subtype"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.job_id} - {self.labour_subtype} @ {self.charge_out_rate}"
