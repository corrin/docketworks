"""First-class leave configuration and requests.

Timesheet hours still reach payroll through ``job.CostLine``.  These models
own the higher-level leave intent and keep an explicit link to each generated
line so a range can be managed as one request.
"""

import uuid
from decimal import Decimal
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class LeaveType(models.Model):
    """A fixed Docketworks absence category and its configured shop job."""

    class Code(models.TextChoices):
        ANNUAL = "annual_leave", "Annual Leave"
        SICK = "sick_leave", "Sick Leave"
        UNPAID = "unpaid_leave", "Unpaid Leave"
        BEREAVEMENT = "bereavement_leave", "Bereavement Leave"
        PUBLIC_HOLIDAY = "public_holiday", "Public Holiday"

    code = models.CharField(max_length=32, choices=Code.choices, primary_key=True)
    display_name = models.CharField(max_length=100)
    job = models.OneToOneField(
        "job.Job",
        on_delete=models.PROTECT,
        related_name="leave_type_configuration",
        null=True,
        blank=True,
        help_text=(
            "Special job used for this leave type. Its default Xero pay item is the "
            "single source of the Xero mapping."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["display_name"]

    def __str__(self) -> str:
        return self.display_name

    @property
    def expects_leave_api(self) -> bool:
        """Whether this category must map to a Xero Leave API item."""
        return self.code != self.Code.PUBLIC_HOLIDAY

    @property
    def is_paid(self) -> bool:
        """Whether hours booked to this category are paid."""
        return self.code != self.Code.UNPAID

    @classmethod
    def for_pay_item(cls, pay_item_id: uuid.UUID) -> "LeaveType | None":
        """Return the category a Xero pay item posts, or None where none is configured.

        Opus: The line's own pay item is the only thing that can answer this. "Holiday
        Pay" exists in Xero BOTH as an earnings rate and as a leave type, so a
        name match is ambiguous — and renaming the Xero item reclassified the
        leave silently, which is ADR 0007's "Do not".

        Opus: By id rather than by instance: ``XeroPayItem`` lives in ``apps.xero``,
        which sits ABOVE the domain apps in the import contract, so this module
        cannot name its type.
        """
        return cls.objects.filter(job__default_xero_pay_item_id=pay_item_id).first()

    def clean(self) -> None:
        """Require configured jobs and pay items to match the category's posting surface."""
        if self.job is None:
            return
        if self.job.status != "special":
            raise ValidationError({"job": "Leave types must use a special Docketworks job."})
        pay_item = self.job.default_xero_pay_item
        if pay_item is None:
            raise ValidationError({"job": "The selected job must have a Xero payroll item."})
        if pay_item.uses_leave_api != self.expects_leave_api:
            expected = "leave type" if self.expects_leave_api else "earnings rate"
            raise ValidationError({"job": f"This leave type requires a Xero {expected}."})


class LeaveRequest(models.Model):
    """One administrator-created leave range for one staff member."""

    class Source(models.TextChoices):
        LEAVE = "leave", "Leave"
        OFFICE_CLOSURE = "office_closure", "Office closure"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(
        "accounts.Staff", on_delete=models.PROTECT, related_name="leave_requests"
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, related_name="leave_requests"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    note = models.CharField(  # noqa: DJ001 -- NULL is the explicit unset value (ADR 0040)
        max_length=255, null=True, blank=True
    )
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.LEAVE)
    batch_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        "accounts.Staff", on_delete=models.PROTECT, related_name="created_leave_requests"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["start_date", "staff__last_name", "staff__first_name"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="timesheet_leave_request_date_order",
            ),
            # Opus: ADR 0040's layer 1, which the noqa on ``note`` cited without
            # adding: the office-closure path writes these rows from a service,
            # not through the request schema that rejects a blank.
            models.CheckConstraint(
                condition=~Q(note=""), name="timesheet_leave_request_note_not_blank"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.staff.get_display_name()}: {self.leave_type.display_name}"

    def clean(self) -> None:
        """Reject reversed ranges before the database constraint does."""
        if self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date must be on or after start date."})


class LeaveDay(models.Model):
    """One scheduled day belonging to a leave request and its payroll projection."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="days")
    staff = models.ForeignKey("accounts.Staff", on_delete=models.PROTECT, related_name="leave_days")
    date = models.DateField()
    hours = models.DecimalField(max_digits=6, decimal_places=3)
    cost_line = models.OneToOneField(
        "job.CostLine",
        on_delete=models.PROTECT,
        related_name="leave_day",
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["date"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["staff", "date"], name="unique_staff_leave_day"),
            models.UniqueConstraint(fields=["request", "date"], name="unique_request_leave_day"),
            models.CheckConstraint(
                condition=Q(hours__gt=Decimal("0")), name="timesheet_leave_day_positive_hours"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.request} on {self.date}: {self.hours}h"

    def clean(self) -> None:
        """Keep the denormalised staff key aligned with its parent request."""
        if self.request_id and self.staff_id != self.request.staff_id:
            raise ValidationError({"staff": "Leave day staff must match its request."})
