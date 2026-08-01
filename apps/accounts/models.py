"""The Staff custom user model and its manager, ported from v1 apps/accounts."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.timezone import now as timezone_now
from simple_history.models import HistoricalRecords

from apps.core.models import CompanyDefaults

SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"


class StaffManager(BaseUserManager["Staff"]):
    """Custom manager for the Staff user model.

    Combines type hints for maintainability, strict validation for superuser
    creation, and proper defaults for staff-specific fields.
    """

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> "Staff":
        """Create and save a Staff user with a normalised email address."""
        if not email:
            raise ValueError("The Email field must be set")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields: Any) -> "Staff":
        """Create a superuser, requiring office-staff and superuser flags."""
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
        """Get currently active staff (replaces is_active=True filters)."""
        return self.active_on_date(timezone.localdate())

    def active_between_dates(self, start_date: date, end_date: date) -> "models.QuerySet[Staff]":
        """Get staff members who were employed at any point during the date range."""
        return self.filter(date_joined__date__lte=end_date).filter(
            models.Q(date_left__isnull=True) | models.Q(date_left__gte=start_date)
        )


class Staff(AbstractBaseUser, PermissionsMixin):
    """Custom user model.

    API exposure is defined by the ninja schemas in apps/accounts/schemas.py —
    the single source of Staff field lists in v2.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    icon = models.ImageField(upload_to="staff_icons/", null=True, blank=True)
    password_needs_reset = models.BooleanField(default=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    preferred_name = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset (CLAUDE.md migration rule)
        max_length=30, blank=True, null=True
    )
    base_wage_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Actual hourly pay rate. wage_rate is auto-computed with leave loading.",
    )
    wage_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    xero_user_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    date_left = models.DateField(
        null=True,
        blank=True,
        help_text="Date staff member left employment (null for current employees)",
    )
    is_office_staff = models.BooleanField(default=False)
    is_workshop_staff = models.BooleanField(default=True)
    default_labour_subtype = models.ForeignKey(
        "job.LabourSubtype",
        on_delete=models.PROTECT,
        related_name="default_for_staff",
        null=True,
        blank=True,
        help_text=(
            "Labour subtype preselected on new timesheet entries. "
            "Auto-set from is_workshop_staff when blank."
        ),
    )
    date_joined = models.DateTimeField(default=timezone.now)
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
    REQUIRED_FIELDS: ClassVar[list[str]] = [
        "first_name",
        "last_name",
    ]

    class Meta:
        ordering: ClassVar[list[str]] = ["last_name", "first_name"]
        verbose_name = "Staff Member"
        verbose_name_plural = "Staff Members"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(preferred_name=""), name="preferred_name_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(xero_user_id=""), name="xero_user_id_not_blank"
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the row, refreshing updated_at and the computed wage_rate."""
        # We have to do this because fixtures don't have updated_at,
        # so auto_now_add doesn't work
        self.updated_at = timezone_now()

        # Auto-compute wage_rate from base_wage_rate + annual leave loading
        # Skip if update_fields is specified and doesn't include base_wage_rate
        # (avoids circular recompute when CompanyDefaults bulk-updates wage_rate)
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "base_wage_rate" in update_fields:
            self._compute_wage_rate()

        if self.default_labour_subtype_id is None and (
            update_fields is None or "default_labour_subtype" in update_fields
        ):
            self._set_default_labour_subtype()

        super().save(*args, **kwargs)

    def _set_default_labour_subtype(self) -> None:
        """Default to the first active subtype matching is_workshop_staff."""
        # Deferred import: apps.job imports Staff transitively at module level.
        from apps.job.models import LabourSubtype  # noqa: PLC0415

        if self.is_workshop_staff:
            self.default_labour_subtype = LabourSubtype.default_workshop()
        else:
            self.default_labour_subtype = LabourSubtype.default_non_workshop()

    def _compute_wage_rate(self) -> None:
        """Set wage_rate = base_wage_rate * (1 + annual_leave_loading/100)."""
        if not self.base_wage_rate:
            self.wage_rate = Decimal("0")
            return
        # ADR 0015: no read-side fallback (v1 substituted 8.00 here — dead code
        # via get_solo's get_or_create, and contradicting the real 20.00
        # default). If the singleton genuinely cannot exist, crashing is correct.
        loading = CompanyDefaults.get_solo().annual_leave_loading
        multiplier = Decimal("1") + loading / Decimal("100")
        self.wage_rate = (Decimal(str(self.base_wage_rate)) * multiplier).quantize(Decimal("0.01"))

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def get_scheduled_hours(self, target_date: date) -> float:
        """Get expected working hours for a specific date."""
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
        """Return the first word of the preferred name, falling back to first_name."""
        display = self.preferred_name or self.first_name
        return display.split()[0] if display else ""

    def get_display_full_name(self) -> str:
        """Return the display name followed by the last name."""
        return f"{self.get_display_name()} {self.last_name}"

    def is_staff_manager(self) -> bool:
        """Check StaffManager group membership (superusers always qualify)."""
        return self.groups.filter(name="StaffManager").exists() or self.is_superuser

    @classmethod
    def get_automation_user(cls) -> "Staff":
        """Return the dedicated System Automation staff row.

        Used when a save is initiated by a background job, webhook, data
        migration, or management command — anywhere a specific human staff
        member isn't on the call stack. Seeded by data migration.
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
        """Check if staff member is currently active."""
        return self.date_left is None or self.date_left > timezone.localdate()
