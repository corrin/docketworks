import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


class XeroPayRun(models.Model):
    """
    Represents a Xero PayRun - a batch of pay slips for a pay period.

    PayRuns are the parent container for PaySlips. Each PayRun covers a specific
    pay period (period_start_date to period_end_date) and has a payment_date
    when employees are paid.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    xero_id = models.UUIDField(unique=True)
    xero_tenant_id = models.CharField(max_length=255)

    payroll_calendar_id = models.UUIDField(null=True, blank=True)
    period_start_date = models.DateField()
    period_end_date = models.DateField()
    payment_date = models.DateField()

    pay_run_status = models.CharField(
        max_length=50, null=True, blank=True
    )  # Draft, Posted, etc.
    pay_run_type = models.CharField(
        max_length=50, null=True, blank=True
    )  # Scheduled, Unscheduled, etc.

    total_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    total_pay = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    raw_json = models.JSONField()
    xero_last_modified = models.DateTimeField()
    xero_last_synced = models.DateTimeField(null=True, blank=True, default=timezone.now)
    django_created_at = models.DateTimeField(auto_now_add=True)
    django_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_date"]
        verbose_name = "Xero Pay Run"
        verbose_name_plural = "Xero Pay Runs"

    def __str__(self):
        return f"PayRun {self.payment_date} ({self.period_start_date} - {self.period_end_date})"


class XeroPaySlip(models.Model):
    """
    Represents a Xero PaySlip - an individual employee's pay for a pay period.

    PaySlips contain the breakdown of earnings (hours worked, leave, etc.) and
    deductions (tax, KiwiSaver, etc.) for a single employee in a pay run.

    Key fields for reconciliation:
    - timesheet_hours: Hours from timesheet_earnings_lines (actual worked hours)
    - leave_hours: Hours from leave_earnings_lines (sick, annual leave, etc.)
    - gross_earnings: Total gross pay before deductions
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    xero_id = models.UUIDField(unique=True)
    xero_tenant_id = models.CharField(max_length=255)

    pay_run = models.ForeignKey(
        XeroPayRun, on_delete=models.CASCADE, related_name="pay_slips"
    )

    # Employee reference - stored as UUID from Xero
    # Can be linked to Staff via Staff.xero_user_id
    xero_employee_id = models.UUIDField()
    employee_name = models.CharField(
        max_length=255, null=True, blank=True
    )  # Denormalized for convenience

    # Key payroll amounts
    gross_earnings = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    net_pay = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    # Hours breakdown - extracted from earnings lines for easy querying
    timesheet_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Hours from timesheet_earnings_lines (actual worked hours)",
    )
    leave_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Hours from leave_earnings_lines (sick, annual, etc.)",
    )

    @property
    def total_hours(self) -> Decimal:
        """Total hours = timesheet hours + leave hours."""
        return self.timesheet_hours + self.leave_hours

    raw_json = models.JSONField()
    xero_last_modified = models.DateTimeField()
    xero_last_synced = models.DateTimeField(null=True, blank=True, default=timezone.now)
    django_created_at = models.DateTimeField(auto_now_add=True)
    django_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pay_run__payment_date", "employee_name"]
        verbose_name = "Xero Pay Slip"
        verbose_name_plural = "Xero Pay Slips"
        # One pay slip per employee per pay run
        unique_together = [["pay_run", "xero_employee_id"]]

    def __str__(self):
        return f"PaySlip {self.employee_name} - {self.pay_run.payment_date}"
