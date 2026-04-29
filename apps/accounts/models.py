import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar, List, Optional

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.timezone import now as timezone_now
from simple_history.models import HistoricalRecords

SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"


class StaffManager(BaseUserManager["Staff"]):
    """
    Custom manager for Staff user model that combines:
    - Type hints for better code maintainability
    - Strict validation for superuser creation
    - Proper default values for staff-specific fields
    """

    def create_user(
        self, email: str, password: Optional[str] = None, **extra_fields: Any
    ) -> "Staff":
        if not email:
            raise ValueError("The Email field must be set")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str, password: str, **extra_fields: Any
    ) -> "Staff":
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("wage_rate", 0)  # Default wage rate for superusers

        # Strict validation for superuser status
        if extra_fields.get("is_office_staff") is not True:
            raise ValueError("Superuser must have is_office_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)

    def active_on_date(self, target_date: date) -> "models.QuerySet[Staff]":
        """Get staff members who were employed on a specific date."""
        return self.filter(date_joined__date__lte=target_date).filter(
            models.Q(date_left__isnull=True) | models.Q(date_left__gt=target_date)
        )

    def currently_active(self) -> "models.QuerySet[Staff]":
        """Get currently active staff (replaces is_active=True filters)"""
        return self.active_on_date(timezone.localdate())

    def active_between_dates(
        self, start_date: date, end_date: date
    ) -> "models.QuerySet[Staff]":
        """Get staff members who were employed at any point during the date range."""
        return self.filter(date_joined__date__lte=end_date).filter(
            models.Q(date_left__isnull=True) | models.Q(date_left__gte=start_date)
        )


class Staff(AbstractBaseUser, PermissionsMixin):
    # CHECKLIST - when adding a new field or property to Staff, check these locations:
    #   1. STAFF_API_FIELDS or STAFF_INTERNAL_FIELDS below (if it's a model field)
    #   2. STAFF_API_PROPERTIES below (if it's a computed property for API)
    #   3. KanbanStaffSerializer.Meta.fields in apps/accounts/serializers.py (subset for kanban)
    #   4. _format_staff() in apps/timesheet/services/payroll_employee_sync.py (subset for payroll)
    #   5. staff dict in modern_timesheet_views.py get() method (subset for timesheet)
    #   6. staff_data dict in daily_timesheet_service.py _get_staff_daily_data() (subset for daily view)
    #   7. staff_data dict in timesheet/views/api.py (fallback staff data)
    #   8. ModernStaffSerializer in apps/timesheet/serializers/modern_timesheet_serializers.py (subset)
    #   9. StaffDailyDataSerializer in apps/timesheet/serializers/daily_timesheet_serializers.py (subset)
    #
    # Fields exposed via API (read/write where applicable).
    STAFF_API_FIELDS = [
        "id",
        "email",
        "first_name",
        "last_name",
        "preferred_name",
        "base_wage_rate",
        "wage_rate",
        "xero_user_id",
        "date_left",
        "is_office_staff",
        "is_workshop_staff",
        "is_superuser",
        "password_needs_reset",
        "hours_mon",
        "hours_tue",
        "hours_wed",
        "hours_thu",
        "hours_fri",
        "hours_sat",
        "hours_sun",
        "date_joined",
        "created_at",
        "updated_at",
        "last_login",
        "groups",
        "user_permissions",
    ]

    # Internal fields not exposed via API (write-only or internal use).
    STAFF_INTERNAL_FIELDS = [
        "password",
        "icon",  # Raw ImageField - use icon_url property for API
    ]

    # Computed properties exposed via API (read-only).
    STAFF_API_PROPERTIES = [
        "icon_url",
    ]

    # All fields combined (for internal use).
    STAFF_ALL_FIELDS = STAFF_API_FIELDS + STAFF_INTERNAL_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    icon = models.ImageField(upload_to="staff_icons/", null=True, blank=True)
    password_needs_reset: bool = models.BooleanField(default=False)
    email: str = models.EmailField(unique=True)
    first_name: str = models.CharField(max_length=30)
    last_name: str = models.CharField(max_length=30)
    preferred_name: Optional[str] = models.CharField(
        max_length=30, blank=True, null=True
    )
    base_wage_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Actual hourly pay rate. wage_rate is auto-computed with leave loading.",
    )
    wage_rate: float = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    xero_user_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    date_left = models.DateField(
        null=True,
        blank=True,
        help_text="Date staff member left employment (null for current employees)",
    )
    is_office_staff: bool = models.BooleanField(default=False)
    is_workshop_staff: bool = models.BooleanField(default=True)
    date_joined: datetime = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    hours_mon = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=8.00,
        help_text="Standard hours for Monday, 0 for non-working day",
    )
    hours_tue = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=8.00,
        help_text="Standard hours for Tuesday, 0 for non-working day",
    )
    hours_wed = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=8.00,
        help_text="Standard hours for Wednesday, 0 for non-working day",
    )
    hours_thu = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=8.00,
        help_text="Standard hours for Thursday, 0 for non-working day",
    )
    hours_fri = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=8.00,
        help_text="Standard hours for Friday, 0 for non-working day",
    )
    hours_sat = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0.00,
        help_text="Standard hours for Saturday, 0 for non-working day",
    )
    hours_sun = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0.00,
        help_text="Standard hours for Sunday, 0 for non-working day",
    )

    history: HistoricalRecords = HistoricalRecords()

    objects = StaffManager()

    USERNAME_FIELD: str = "email"
    REQUIRED_FIELDS: ClassVar[List[str]] = [
        "first_name",
        "last_name",
    ]

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "Staff Member"
        verbose_name_plural = "Staff Members"

    def save(self, *args: Any, **kwargs: Any) -> None:
        # We have to do this because fixtures don't have updated_at,
        # so auto_now_add doesn't work
        self.updated_at = timezone_now()

        # Auto-compute wage_rate from base_wage_rate + annual leave loading
        # Skip if update_fields is specified and doesn't include base_wage_rate
        # (avoids circular recompute when CompanyDefaults bulk-updates wage_rate)
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "base_wage_rate" in update_fields:
            self._compute_wage_rate()

        super().save(*args, **kwargs)

    def _compute_wage_rate(self) -> None:
        """Set wage_rate = base_wage_rate * (1 + annual_leave_loading/100)."""
        if not self.base_wage_rate:
            self.wage_rate = Decimal("0")
            return
        from apps.workflow.models import CompanyDefaults

        try:
            loading = CompanyDefaults.get_solo().annual_leave_loading
        except CompanyDefaults.DoesNotExist:
            loading = Decimal("8.00")
        multiplier = Decimal("1") + loading / Decimal("100")
        self.wage_rate = (Decimal(str(self.base_wage_rate)) * multiplier).quantize(
            Decimal("0.01")
        )

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def get_scheduled_hours(self, target_date: date) -> float:
        """Get expected working hours for a specific date"""
        weekday = target_date.weekday()
        hours_by_day = [
            self.hours_mon,
            self.hours_tue,
            self.hours_wed,
            self.hours_thu,
            self.hours_fri,
            self.hours_sat,
            self.hours_sun,
        ]
        return float(hours_by_day[weekday])

    def get_display_name(self) -> str:
        display = self.preferred_name or self.first_name

        display = display.split()[0] if display else ""

        return display

    def get_display_full_name(self) -> str:
        display_name = self.get_display_name()
        full_name = f"{display_name} {self.last_name}"
        return full_name

    def is_staff_manager(self) -> bool:
        return self.groups.filter(name="StaffManager").exists() or self.is_superuser

    @classmethod
    def get_automation_user(cls) -> "Staff":
        """Return the dedicated System Automation staff row.

        Used when a save is initiated by a background job, webhook, data
        migration, or management command — anywhere a specific human staff
        member isn't on the call stack. The row is seeded by migration
        accounts.0015 and carries no privileges.
        """
        try:
            return cls.objects.get(email=SYSTEM_AUTOMATION_EMAIL)
        except cls.DoesNotExist as exc:
            raise RuntimeError(
                f"System Automation staff ({SYSTEM_AUTOMATION_EMAIL}) is missing. "
                "Run `python manage.py migrate` to seed it."
            ) from exc

    @property
    def is_currently_active(self) -> bool:
        """Check if staff member is currently active"""
        return self.date_left is None or self.date_left > timezone.localdate()

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @name.setter
    def name(self, value: str) -> None:
        parts = value.split()
        if len(parts) >= 2:
            self.first_name = parts[0]
            self.last_name = " ".join(parts[1:])
        else:
            raise ValueError("Name must include both first and last name")
