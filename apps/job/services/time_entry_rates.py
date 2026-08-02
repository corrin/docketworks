"""The ONE implementation of time-entry rate resolution (ADR 0039).

Ported from v1 ``apps/job/services/time_entry_rates.py`` plus the three
divergent pipelines that sat on top of it:

1. ``apps/job/serializers/costing_serializer.py`` ``CostLineCreateUpdateSerializer.save()``
   — repriced ``meta.created_from_timesheet`` lines on create and on a
   labour-subtype change. Job-aware pay item (leave jobs), wage rate from
   ``Staff.wage_rate`` falling back to ``CompanyDefaults.wage_rate``.
2. ``apps/job/views/modern_timesheet_views.py`` ``ModernTimesheetEntryView.post()``
   — same job-aware pay item and leave handling, wage rate from an explicit
   override else ``Staff.wage_rate``.
3. ``apps/job/services/workshop_service.py`` — wage rate from ``Staff.wage_rate``
   only, and pay item resolved from the multiplier ALONE, so a workshop staffer
   booking their own time against a Leave job got an earnings-rate pay item and
   a billable line instead of leave at zero bill rate.

(3) is the odd one out and is a bug, so v2 keeps the (1)/(2) behaviour as the
single canonical pipeline: ``price_time_entry`` below. Every caller — cost-line
writes, the workshop my-time surface — goes through it, so the rates can never
fork again.

One v1 behaviour is deliberately NOT kept from either pipeline: the missing-wage
fallbacks. (1) substituted ``CompanyDefaults.wage_rate`` and (3) costed the line
at 0.00, so a staff member whose wage rate was never configured silently
produced wrong job costs. Per ADR 0015 and the user decision of 2026-08-03,
``staff_wage_rate`` raises instead, naming the staff member; every write
endpoint that prices time surfaces it as a 400.

Layer contract: ``XeroPayItem`` lives in ``apps.xero``, which sits ABOVE the
domain apps, so it is resolved through Django's app registry behind the
``PayItem`` protocol (the pattern ``apps/core/models.py`` uses for
``_WageBearingStaff``), never imported.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast
from uuid import UUID

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError

from apps.job.models import Job, JobLabourRate, LabourSubtype

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
DEFAULT_MULTIPLIER = Decimal("1.00")
ZERO_MULTIPLIER = Decimal("0.00")


class PayItem(Protocol):
    """Structural view of ``xero.XeroPayItem`` used by time-entry pricing.

    Read-only members: the pipeline only ever reads a pay item, and the FK is
    assigned by id, so nothing here needs the concrete model class.
    """

    @property
    def id(self) -> UUID:
        """The pay item's primary key."""

    @property
    def name(self) -> str:
        """The pay item's display name (e.g. 'Ordinary Time')."""

    @property
    def uses_leave_api(self) -> bool:
        """Whether the item posts through Xero's Leave API."""

    @property
    def xero_id(self) -> str | None:
        """Xero's own id, absent until the tenant is connected."""

    @property
    def multiplier(self) -> Decimal | None:
        """The item's rate multiplier; None for leave types."""


class _PayItemCatalogue(Protocol):
    """The ``XeroPayItem`` classmethod surface the pipeline needs."""

    def get_by_multiplier(self, multiplier: Decimal) -> PayItem | None:
        """Return the earnings rate for a multiplier, or None."""


def _pay_item_catalogue() -> _PayItemCatalogue:
    """Resolve the XeroPayItem class through the app registry (layer contract)."""
    return cast("_PayItemCatalogue", django_apps.get_model("xero", "XeroPayItem"))


def to_decimal(value: object, *, default: Decimal = DEFAULT_MULTIPLIER) -> Decimal:
    """Coerce a JSON/meta scalar to Decimal, falling back to ``default`` (v1)."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def normalize_multiplier(value: object, *, default: Decimal = DEFAULT_MULTIPLIER) -> Decimal:
    """Coerce a rate multiplier to two decimal places (v1)."""
    return to_decimal(value, default=default).quantize(CENT)


def get_bill_rate_multiplier(meta: dict[str, object], wage_rate_multiplier: Decimal) -> Decimal:
    """Derive the bill-rate multiplier implied by a line's meta (v1).

    Explicit ``bill_rate_multiplier`` wins; an explicit non-billable flag
    means zero; otherwise the bill multiplier tracks the wage multiplier.
    """
    explicit = meta.get("bill_rate_multiplier")
    if "bill_rate_multiplier" in meta and explicit is not None:
        return normalize_multiplier(explicit)

    if meta.get("is_billable") is False:
        return ZERO_MULTIPLIER

    return normalize_multiplier(wage_rate_multiplier)


def resolve_xero_pay_item(wage_rate_multiplier: Decimal) -> PayItem:
    """Resolve the earnings-rate pay item for a wage multiplier; fail early if absent (v1)."""
    normalized = normalize_multiplier(wage_rate_multiplier)
    pay_item = _pay_item_catalogue().get_by_multiplier(normalized)
    if pay_item is None:
        raise ValidationError(f"No Xero pay item found for wage_rate_multiplier={normalized}.")
    return pay_item


def is_leave_pay_item(pay_item: PayItem | None) -> bool:
    """Whether the pay item is posted through Xero's Leave API rather than timesheets."""
    return pay_item is not None and pay_item.uses_leave_api


def leave_wage_rate_multiplier(pay_item: PayItem) -> Decimal:
    """Leave is paid at 1x unless the pay item is an unpaid-leave type (v1)."""
    if "unpaid" in pay_item.name.lower():
        return ZERO_MULTIPLIER
    return DEFAULT_MULTIPLIER


def resolve_xero_pay_item_for_job(*, job: Job, wage_rate_multiplier: Decimal) -> PayItem:
    """Resolve the pay item for time on this job: its leave type, else the earnings rate (v1).

    Leave jobs (``default_xero_pay_item.uses_leave_api``) always post through
    the Leave API, so their pay item wins over the multiplier lookup.
    """
    job_pay_item: PayItem | None = job.default_xero_pay_item
    if is_leave_pay_item(job_pay_item):
        # Narrowing for the type checker: is_leave_pay_item is None-safe.
        if job_pay_item is None:  # pragma: no cover - unreachable, guards the narrowing
            raise ValidationError(f"Leave job '{job.name}' lost its pay item mid-resolution.")
        if not job_pay_item.xero_id:
            raise ValidationError(
                f"Leave job '{job.name}' has Xero pay item '{job_pay_item.name}' with no xero_id."
            )
        return job_pay_item
    return resolve_xero_pay_item(wage_rate_multiplier)


@dataclass(frozen=True, slots=True)
class TimeUnitRates:
    """Per-hour cost/revenue for a time line plus the base rates they came from."""

    unit_cost: Decimal
    unit_rev: Decimal
    wage_rate: Decimal
    charge_out_rate: Decimal


def calculate_time_unit_rates(
    *,
    wage_rate: object,
    charge_out_rate: object,
    wage_rate_multiplier: Decimal,
    bill_rate_multiplier: Decimal,
) -> TimeUnitRates:
    """Apply the wage/bill multipliers to the base rates (v1, cent-quantized)."""
    base_wage_rate = to_decimal(wage_rate, default=Decimal("0")).quantize(CENT)
    base_charge_out_rate = to_decimal(charge_out_rate, default=Decimal("0")).quantize(CENT)
    wage_multiplier = normalize_multiplier(wage_rate_multiplier)
    bill_multiplier = normalize_multiplier(bill_rate_multiplier)
    return TimeUnitRates(
        unit_cost=(base_wage_rate * wage_multiplier).quantize(CENT),
        unit_rev=(base_charge_out_rate * bill_multiplier).quantize(CENT),
        wage_rate=base_wage_rate,
        charge_out_rate=base_charge_out_rate,
    )


class WageBearingStaff(Protocol):
    """The Staff surface time-entry pricing reads (identity + wage rate + default subtype)."""

    @property
    def id(self) -> UUID:
        """The staff member's primary key."""

    @property
    def wage_rate(self) -> Decimal:
        """The staff member's loaded hourly cost rate."""

    @property
    def default_labour_subtype(self) -> LabourSubtype | None:
        """The subtype new time entries default to."""

    def get_display_full_name(self) -> str:
        """Return the staff member's display name, for error messages."""


@dataclass(frozen=True, slots=True)
class TimeEntryPricing:
    """Everything a priced time line needs: rates, multipliers and the pay item."""

    unit_cost: Decimal
    unit_rev: Decimal
    wage_rate: Decimal
    charge_out_rate: Decimal
    wage_rate_multiplier: Decimal
    bill_rate_multiplier: Decimal
    is_billable: bool
    pay_item: PayItem
    labour_subtype: LabourSubtype

    def meta_updates(self) -> dict[str, object]:
        """Build the meta keys v1 wrote back onto a priced timesheet line."""
        return {
            "wage_rate_multiplier": float(self.wage_rate_multiplier),
            "bill_rate_multiplier": float(self.bill_rate_multiplier),
            "is_billable": self.is_billable,
            "wage_rate": float(self.wage_rate),
            "charge_out_rate": float(self.charge_out_rate),
        }


def resolve_labour_subtype(
    *, staff: WageBearingStaff, explicit: LabourSubtype | None
) -> LabourSubtype:
    """Resolve the line's labour subtype: the explicit one, else the worker's default (v1)."""
    if explicit is not None:
        return explicit
    default = staff.default_labour_subtype
    if default is None:
        raise ValidationError(
            "labour_subtype is required for time entries and staff "
            f"{staff.id} has no default_labour_subtype."
        )
    return default


def job_charge_out_rate(job: Job, labour_subtype: LabourSubtype) -> Decimal:
    """Read the job's charge-out rate for a labour subtype; fail early if unset (v1)."""
    try:
        rate = JobLabourRate.objects.get(job=job, labour_subtype=labour_subtype)
    except JobLabourRate.DoesNotExist as exc:
        raise ValidationError(
            f"Job {job.id} has no labour rate for subtype {labour_subtype.name}."
        ) from exc
    return rate.charge_out_rate


def staff_wage_rate(staff: WageBearingStaff, override: Decimal | None = None) -> Decimal:
    """Return the hourly cost rate to price a staff member's time at; fail early if unset.

    Neither v1 fallback survives (user decision 2026-08-03, ADR 0015): the
    costing pipeline substituted ``CompanyDefaults.wage_rate`` and the workshop
    pipeline costed the time at 0.00, so an unconfigured staff member silently
    produced wrong job costs instead of an obvious error. The message names the
    staff member so the fix is a single edit on their record (ADR 0038).
    """
    wage_rate = override if override is not None else staff.wage_rate
    if not wage_rate:
        raise ValidationError(
            f"Wage rate is not configured for staff {staff.get_display_full_name()} "
            f"({staff.id}); set their base wage rate before booking time."
        )
    return wage_rate


def price_time_entry(
    *,
    job: Job,
    staff: WageBearingStaff,
    meta: dict[str, object],
    labour_subtype: LabourSubtype | None = None,
    wage_rate_override: Decimal | None = None,
) -> TimeEntryPricing:
    """Price one time entry — the single rate-resolution path for the whole app.

    ``meta`` supplies ``wage_rate_multiplier`` (required, as v1) plus the
    optional ``bill_rate_multiplier``/``is_billable`` billing intent. Leave
    jobs override both multipliers: leave is paid at 1x (0x when unpaid) and is
    never billable.
    """
    raw_multiplier = meta.get("wage_rate_multiplier")
    if raw_multiplier is None:
        raise ValidationError(
            "Rate multiplier must be provided when creating a new timesheet entry."
        )

    subtype = resolve_labour_subtype(staff=staff, explicit=labour_subtype)
    wage_rate = staff_wage_rate(staff, wage_rate_override)
    wage_rate_multiplier = normalize_multiplier(raw_multiplier)
    pay_item = resolve_xero_pay_item_for_job(job=job, wage_rate_multiplier=wage_rate_multiplier)
    if is_leave_pay_item(pay_item):
        wage_rate_multiplier = leave_wage_rate_multiplier(pay_item)
        bill_rate_multiplier = ZERO_MULTIPLIER
    else:
        bill_rate_multiplier = get_bill_rate_multiplier(meta, wage_rate_multiplier)

    rates = calculate_time_unit_rates(
        wage_rate=wage_rate,
        charge_out_rate=job_charge_out_rate(job, subtype),
        wage_rate_multiplier=wage_rate_multiplier,
        bill_rate_multiplier=bill_rate_multiplier,
    )
    return TimeEntryPricing(
        unit_cost=rates.unit_cost,
        unit_rev=rates.unit_rev,
        wage_rate=rates.wage_rate,
        charge_out_rate=rates.charge_out_rate,
        wage_rate_multiplier=wage_rate_multiplier,
        bill_rate_multiplier=bill_rate_multiplier,
        is_billable=bill_rate_multiplier > ZERO_MULTIPLIER,
        pay_item=pay_item,
        labour_subtype=subtype,
    )
