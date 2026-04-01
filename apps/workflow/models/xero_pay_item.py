"""
XeroPayItem model - synced from Xero Leave Types and Earnings Rates.

This model stores the pay items (leave types and earnings rates) that are
configured in Xero Payroll. These are used to categorize time entries
when posting to Xero.
"""

import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


class XeroPayItem(models.Model):
    """
    Represents a Xero pay item - either a Leave Type or an Earnings Rate.

    Synced from Xero via:
    - get_leave_types() → uses_leave_api=True
    - get_earnings_rates() → uses_leave_api=False

    Examples:
    - "Annual Leave" (leave type, uses_leave_api=True, multiplier=NULL)
    - "Ordinary Time" (earnings rate, uses_leave_api=False, multiplier=1.0)
    - "Time and one half" (earnings rate, uses_leave_api=False, multiplier=1.5)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Xero identifiers — nullable because records are loaded from backup
    # without Xero IDs. They get populated when the target environment
    # connects to its own Xero via `xero --configure-payroll`.
    xero_id = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text="Xero's UUID for this pay item",
    )
    xero_tenant_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Xero tenant this pay item belongs to",
    )

    # Pay item details
    name = models.CharField(
        max_length=100,
        help_text="Display name (e.g., 'Ordinary Time', 'Annual Leave')",
    )

    uses_leave_api = models.BooleanField(
        help_text="True = Xero Leave API, False = Xero Timesheets API",
    )

    multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Rate multiplier from Xero (1.0, 1.5, 2.0, etc.). NULL for leave types.",
    )

    # Sync metadata
    xero_last_modified = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last modified timestamp from Xero",
    )
    xero_last_synced = models.DateTimeField(
        null=True,
        blank=True,
        default=timezone.now,
        help_text="When we last synced this record from Xero",
    )

    # Django timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["uses_leave_api", "name"]
        verbose_name = "Xero Pay Item"
        verbose_name_plural = "Xero Pay Items"
        constraints = [
            models.UniqueConstraint(
                fields=["name", "uses_leave_api"],
                name="unique_pay_item_name_per_api",
            ),
        ]

    def __str__(self) -> str:
        if self.multiplier:
            return f"{self.name} ({self.multiplier}x)"
        return self.name

    @classmethod
    def get_by_multiplier(cls, multiplier: Decimal) -> "XeroPayItem | None":
        """Get a XeroPayItem by rate multiplier."""
        return cls.objects.filter(
            uses_leave_api=False,
            multiplier=multiplier,
        ).first()

    @classmethod
    def get_ordinary_time(cls) -> "XeroPayItem | None":
        """Get the 'Ordinary Time' pay item by name."""
        return cls.objects.filter(
            name="Ordinary Time",
            uses_leave_api=False,
        ).first()
