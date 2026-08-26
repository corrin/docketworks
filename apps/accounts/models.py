"""The Staff custom user model and its manager."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.timezone import now as timezone_now
from simple_history.models import HistoricalRecords

from apps.core.models import CompanyDefaults

SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"

# The one Django group with meaning: is_staff_manager() checks it and the
# staff admin API's checkbox manages it. Seeded nowhere — writers get_or_create.
STAFF_MANAGER_GROUP_NAME = "StaffManager"


class StaffManager(BaseUserManager["Staff"]):
    """Custom manager for the Staff user model.

    Combines type hints for maintainability, strict validation for superuser
    creation, and proper defaults for staff-specific fields.
    """

    def create_user(
        self, office_email: str | None, password: str | None = None, **extra_fields: Any
    ) -> "Staff":
        """Create and save a Staff user with a normalised office email."""
        if not office_email and not extra_fields.get("payroll_email"):
            raise ValueError("A staff member needs at least one email address.")

        if office_email is not None:
            office_email = self.normalize_email(office_email)
        # Fable: payroll_email is stored verbatim as Xero holds it — the login
        # backend matches with iexact, so normalising it here would diverge
        # from the sync's direct writes without buying anything.
        user = self.model(office_email=office_email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, office_email: str, password: str, **extra_fields: Any) -> "Staff":
        """Create a superuser, requiring office-staff and superuser flags."""
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("wage_rate", 0)  # Default wage rate for superusers

        # Strict validation for superuser status
        if extra_fields.get("is_office_staff") is not True:
            raise ValueError("Superuser must have is_office_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(office_email, password, **extra_fields)

    def active_on_date(self, target_date: date) -> "models.QuerySet[Staff]":
        """Get staff members who were employed on a specific date."""
        return self.filter(employment_start_date__lte=target_date).filter(
            models.Q(date_left__isnull=True) | models.Q(date_left__gt=target_date)
        )

    def currently_active(self) -> "models.QuerySet[Staff]":
        """Get currently active staff (replaces is_active=True filters)."""
        return self.active_on_date(timezone.localdate())

    def active_between_dates(self, start_date: date, end_date: date) -> "models.QuerySet[Staff]":
        """Get staff members who were employed at any point during the date range."""
        return self.filter(employment_start_date__lte=end_date).filter(
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
    # Fable: neither address is individually required — wage staff often have
    # only a payroll mailbox, office staff often only this one (owner ruling
    # 2026-08-26). The staff_at_least_one_email constraint holds the floor,
    # and StaffEmailBackend signs a staff member in with either address.
    office_email = models.EmailField(unique=True, null=True, blank=True)
    payroll_email = models.EmailField(unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    preferred_name = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
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
    # Which Xero organisation xero_user_id belongs to. A restored production
    # dump carries the id with this NULL, which is how the seed's employees
    # phase tells "linked in production" from "linked here" and how its
    # convergence measure knows the mirror is not finished. Same shape as
    # Company.xero_tenant_id; we are not multi-tenant.
    xero_tenant_id = models.CharField(  # noqa: DJ001 -- NULL means "not linked to any organisation"
        max_length=255, null=True, blank=True
    )
    xero_last_modified = models.DateTimeField(null=True, blank=True)
    employment_start_date = models.DateField(default=timezone.localdate)
    pay_basis = models.CharField(  # noqa: DJ001 -- NULL means not classified by payroll
        max_length=10,
        choices=(("hourly", "Hourly"), ("salary", "Salary")),
        null=True,
        blank=True,
    )
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

    USERNAME_FIELD: str = "office_email"
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
            models.CheckConstraint(
                condition=~models.Q(xero_tenant_id=""), name="staff_xero_tenant_id_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(payroll_email=""), name="staff_payroll_email_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(pay_basis=""), name="staff_pay_basis_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(office_email=""), name="staff_office_email_not_blank"
            ),
            models.CheckConstraint(
                condition=models.Q(office_email__isnull=False)
                | models.Q(payroll_email__isnull=False),
                name="staff_at_least_one_email",
                violation_error_message="A staff member needs at least one email address.",
            ),
            # Fable: the database's answer to the race clean() cannot close —
            # two concurrent writes of case-variant emails both pass the
            # iexact query and both save, and StaffEmailBackend then locks
            # both accounts out. clean() stays for the user-facing 400.
            # Both login columns need it: the backend matches each with iexact.
            models.UniqueConstraint(Lower("office_email"), name="staff_office_email_ci_unique"),
            models.UniqueConstraint(Lower("payroll_email"), name="staff_payroll_email_ci_unique"),
        ]

    def clean(self) -> None:
        """Normalise the login email and enforce its case-insensitive uniqueness.

        Fable: the column's UNIQUE constraint is case-sensitive, but
        StaffEmailBackend matches office_email with iexact and returns None on
        multiple hits — so a case-variant duplicate would silently lock BOTH
        accounts out of login. full_clean is the write-path gate the staff
        admin endpoints already run, so the check lives here, not in a handler.
        """
        super().clean()
        if self.payroll_email is not None:
            payroll_collision = (
                Staff.objects.exclude(pk=self.pk)
                .filter(payroll_email__iexact=self.payroll_email)
                .exists()
            )
            if payroll_collision:
                raise ValidationError("A staff member with this payroll email already exists.")
        if self.office_email is None:
            # Fable: normalize_email coerces None to "" (email or "") — running
            # it on an unset address would launder NULL into the blank string
            # every constraint forbids (ADR 0040), so unset skips this block.
            return
        self.office_email = StaffManager.normalize_email(self.office_email)
        collision = (
            Staff.objects.exclude(pk=self.pk)
            .filter(office_email__iexact=self.office_email)
            .exists()
        )
        if collision:
            raise ValidationError("A staff member with this office email already exists.")

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

    def get_scheduled_hours(self, target_date: date) -> Decimal:
        """Get expected working hours for a specific date.

        Opus: Decimal because the columns are: returning float here meant the daily
        service parsed it straight back with ``Decimal(str(...))``, a round
        trip whose only effect was the chance of losing a digit on the way.
        """
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
        return Decimal(hours_by_day[weekday])

    def get_display_name(self) -> str:
        """Return the first word of the preferred name, falling back to first_name."""
        display = self.preferred_name or self.first_name
        return display.split()[0] if display else ""

    def get_display_full_name(self) -> str:
        """Return the display name followed by the last name."""
        return f"{self.get_display_name()} {self.last_name}"

    def is_staff_manager(self) -> bool:
        """Check StaffManager group membership (superusers always qualify)."""
        return self.groups.filter(name=STAFF_MANAGER_GROUP_NAME).exists() or self.is_superuser

    @classmethod
    def get_automation_user(cls) -> "Staff":
        """Return the dedicated System Automation staff row.

        Used when a save is initiated by a background job, webhook, data
        migration, or management command — anywhere a specific human staff
        member isn't on the call stack. Seeded by data migration.
        """
        try:
            return cls.objects.get(office_email=SYSTEM_AUTOMATION_EMAIL)
        except cls.DoesNotExist as exc:
            raise RuntimeError(
                f"System Automation staff ({SYSTEM_AUTOMATION_EMAIL}) is missing. "
                "Run `python manage.py migrate` to seed it."
            ) from exc

    @property
    def is_currently_active(self) -> bool:
        """Check if staff member is currently active."""
        return self.date_left is None or self.date_left > timezone.localdate()

    def is_active_on(self, target_date: date) -> bool:
        """Whether this staff member was employed on the date.

        Fable: The per-object twin of ``StaffManager.active_on_date``, kept
        beside the manager so the boundary rule cannot fork: employment starts
        ON ``employment_start_date`` and ends strictly BEFORE ``date_left``.
        ``leave_service`` and the payroll push each restated this in Python,
        one edit away from disagreeing with the queryset filters.
        """
        if self.employment_start_date > target_date:
            return False
        return self.date_left is None or self.date_left > target_date

    def is_active_between(self, start_date: date, end_date: date) -> bool:
        """Whether this staff member was employed at any point in the range.

        Fable: The per-object twin of ``StaffManager.active_between_dates``.
        Unlike ``is_active_on``, ``date_left`` compares INCLUSIVELY here
        (``>= start_date``) — that is the manager's own boundary, mirrored
        exactly rather than re-derived.
        """
        if self.employment_start_date > end_date:
            return False
        return self.date_left is None or self.date_left >= start_date


class StaffPayrollTerm(models.Model):
    """One effective-dated salary/wage and working-pattern snapshot from Xero."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name="payroll_terms")
    effective_from = models.DateField()
    pay_basis = models.CharField(
        max_length=10, choices=(("hourly", "Hourly"), ("salary", "Salary"))
    )
    annual_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # One to thirteen repeating weeks, each with monday..sunday numeric hours.
    working_weeks = models.JSONField(default=list)
    # Xero may omit either identity; ADR 0040 requires NULL rather than a blank sentinel.
    xero_salary_wage_id = models.CharField(  # noqa: DJ001
        max_length=255, null=True, blank=True
    )
    xero_working_pattern_id = models.CharField(  # noqa: DJ001
        max_length=255, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["staff_id", "effective_from"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["staff", "effective_from"], name="unique_staff_payroll_term_date"
            ),
            # Opus: ADR 0040's layer 1. The comment above the columns cited the ADR
            # and stopped there, which left the rule enforced nowhere: these are
            # written by the Xero employee sync, and a non-API writer is exactly
            # the case the constraint exists for.
            models.CheckConstraint(
                condition=~models.Q(xero_salary_wage_id=""),
                name="payroll_term_salary_wage_id_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(xero_working_pattern_id=""),
                name="payroll_term_working_pattern_id_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.staff} from {self.effective_from} ({self.pay_basis})"
