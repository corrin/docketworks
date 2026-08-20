"""The canonical implementation of time-entry rate resolution (ADR 0039).

Every caller, including cost-line writes and the workshop my-time surface, uses
``price_time_entry``. Keeping job-aware pay-item selection, leave handling, wage
rates, and bill rates in one pipeline prevents those rules from diverging.

A missing staff wage rate is an input error, not permission to silently use a
global default or zero cost. Per ADR 0015, ``staff_wage_rate`` raises with the
staff member's name and write endpoints surface the failure as a 400 response.

Layer contract: ``XeroPayItem`` lives in ``apps.xero``, which sits ABOVE the
domain apps, so it is resolved through Django's app registry behind the
``PayItem`` protocol (the pattern ``apps/core/models.py`` uses for
``_WageBearingStaff``), never imported.
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast
from uuid import UUID

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.accounts.services.payroll_terms import salary_cost_rate, salary_term_on
from apps.job.models import Job, JobLabourRate, LabourSubtype
from apps.timesheet.models import LeaveType, PostingSurface

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


class _PayItemManager(Protocol):
    def get(self, *, id: UUID) -> PayItem:
        """Return a pay item by its local identifier."""


class _PayItemModel(_PayItemCatalogue, Protocol):
    objects: _PayItemManager


def _pay_item_catalogue() -> _PayItemModel:
    """Resolve the XeroPayItem class through the app registry (layer contract)."""
    return cast("_PayItemModel", django_apps.get_model("xero", "XeroPayItem"))


def pay_item_by_id(pay_item_id: UUID) -> PayItem:
    """Resolve a local Xero payroll item without importing the integration app."""
    return _pay_item_catalogue().objects.get(id=pay_item_id)


def rate_from_meta(meta: dict[str, object], key: str) -> Decimal | None:
    """Read a rate out of stored JSON meta as a Decimal; ``None`` when unset.

    The single place a stored rate becomes a Decimal. ``meta`` is
    ``dict[str, object]`` because it is JSON, so the isinstance here is boundary
    validation, not a type probe — everything downstream is typed ``Decimal``
    and no longer re-discriminates (ADR 0028, ADR 0045).

    This replaced a ``to_decimal(value: object, *, default=)`` that every caller
    reached for. Accepting four types and coercing with ``str()`` let one call
    answer two questions, so a multiplier stored as ``"abc"`` came back as 1.00
    — indistinguishable from unset, silently pricing the line at full rate.
    Absent and JSON null are unset (ADR 0040); a present non-numeric value is
    bad data and raises, because the fix is the row (ADR 0015).

    Safe to raise: dw_cutover_rehearsal holds 26,684 cost lines, 14,474 with a
    wage multiplier and 2,550 with a bill multiplier, and not one fails the
    numeric pattern. No repair migration is needed, so this cannot reject a row
    that exists today.
    """
    value = meta.get(key)
    if value is None:
        return None
    if not isinstance(value, str | int | float | Decimal):
        raise ValidationError(f"{key} must be a number, stored value is {value!r}.")
    try:
        # str() first: Decimal(0.1) captures the binary error, Decimal("0.1")
        # is the number the operator typed.
        rate = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError(f"{key} must be a number, stored value is {value!r}.") from exc
    # Decimal parses "NaN" and "Infinity" happily, so surviving the parse is not
    # proof of a usable number. Infinity then raises InvalidOperation inside
    # quantize() as an uncaught 500, and NaN is worse: it returns quietly and
    # poisons every multiplication after it, pricing the line at NaN. Same
    # defect as _positive_int's non-finite floats in apps/crm.
    if not rate.is_finite():
        raise ValidationError(f"{key} must be a finite number, stored value is {value!r}.")
    return rate


def normalize_multiplier(value: Decimal) -> Decimal:
    """Round a rate multiplier to two decimal places."""
    return value.quantize(CENT)


def get_bill_rate_multiplier(meta: dict[str, object], wage_rate_multiplier: Decimal) -> Decimal:
    """Derive the bill-rate multiplier implied by a line's metadata.

    Explicit ``bill_rate_multiplier`` wins; an explicit non-billable flag
    means zero; otherwise the bill multiplier tracks the wage multiplier.
    """
    explicit = rate_from_meta(meta, "bill_rate_multiplier")
    if explicit is not None:
        return normalize_multiplier(explicit)

    if meta.get("is_billable") is False:
        return ZERO_MULTIPLIER

    return normalize_multiplier(wage_rate_multiplier)


def resolve_xero_pay_item(wage_rate_multiplier: Decimal) -> PayItem:
    """Resolve the earnings-rate pay item for a wage multiplier; fail early if absent."""
    normalized = normalize_multiplier(wage_rate_multiplier)
    pay_item = _pay_item_catalogue().get_by_multiplier(normalized)
    if pay_item is None:
        raise ValidationError(f"No Xero pay item found for wage_rate_multiplier={normalized}.")
    return pay_item


def is_leave_pay_item(pay_item: PayItem | None) -> bool:
    """Whether the pay item is posted through Xero's Leave API rather than timesheets."""
    return pay_item is not None and pay_item.uses_leave_api


def leave_wage_rate_multiplier(pay_item: PayItem) -> Decimal:
    """Whether leave on this pay item is paid, from its configured Docketworks category.

    Opus: Read from ``LeaveType``, never from the pay item's NAME. The match this
    replaces (``"unpaid" in pay_item.name.lower()``) meant an admin renaming the
    Xero item — which the leave-settings screen invites — turned unpaid leave
    into paid leave at full cost, silently (ADR 0007's "Do not").

    Opus: An unmapped leave item is refused rather than assumed paid. The connected
    organisation holds 18 leave-API pay items and Docketworks maps four; the
    other fourteen have no job and no cost line, so refusing costs nothing
    today — and two of them ("Unpaid Sick Leave", "Unpaid Domestic Violence
    Leave") are UNPAID, so assuming paid would reintroduce the same
    overpayment this function exists to prevent, for the next category anyone
    configures (ADR 0015).
    """
    leave_type = LeaveType.for_pay_item(pay_item.id)
    if leave_type is None:
        raise ValidationError(
            f"Xero leave type '{pay_item.name}' is not mapped to a Docketworks leave "
            "category, so whether it is paid is unknown. Map it under "
            "Timesheets -> Leave settings before booking time against it."
        )
    return DEFAULT_MULTIPLIER if leave_type.is_paid else ZERO_MULTIPLIER


def resolve_xero_pay_item_for_job(*, job: Job, wage_rate_multiplier: Decimal) -> PayItem | None:
    """Resolve the job's leave pay item or the staff member's earnings rate.

    Leave jobs (``default_xero_pay_item.uses_leave_api``) always post through
    the Leave API, so their pay item wins over the multiplier lookup.

    Opus: Returns None for a category Xero pays from its own calculation. Its job
    still carries Ordinary Time as a dropdown default — the column is NOT NULL
    — and returning that would put public-holiday hours on the Timesheets API
    on top of the line Xero computes itself, which is the day paid twice.
    """
    # Opus: The reverse side of the OneToOne, not a query per priced line: this
    # runs for every time entry, including every ordinary work line.
    leave_type = getattr(job, "leave_type_configuration", None)
    if leave_type is not None and leave_type.posting_surface is PostingSurface.XERO_COMPUTED:
        return None
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
    wage_rate: Decimal,
    charge_out_rate: Decimal,
    wage_rate_multiplier: Decimal,
    bill_rate_multiplier: Decimal,
) -> TimeUnitRates:
    """Apply the wage/bill multipliers to the base rates.

    The rates arrive as Decimal — staff_wage_rate and job_charge_out_rate both
    raise rather than return None. They were typed `object` and coerced with a
    zero default, which could only have converted a missing rate into free
    labour, the exact substitution staff_wage_rate exists to prevent.
    """
    base_wage_rate = wage_rate.quantize(CENT)
    base_charge_out_rate = charge_out_rate.quantize(CENT)
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
    def pay_basis(self) -> str | None:
        """Whether Xero pays this staff member hourly or by salary."""

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
    #: Opus: None for a category Xero pays from its own calculation — there is no
    #: Xero object to name, and the line is posted nowhere.
    pay_item: PayItem | None
    labour_subtype: LabourSubtype
    salary_term_id: str | None = None

    @property
    def pay_item_id(self) -> "UUID | None":
        """The pay item's id, or None where Xero pays the category from its own calculation.

        Opus: One reader for the three write sites, so a nullable pay item cannot be
        handled correctly in two of them and crash in the third.
        """
        return self.pay_item.id if self.pay_item is not None else None

    def meta_updates(self) -> dict[str, object]:
        """Build the metadata stored on a priced timesheet line."""
        updates: dict[str, object] = {
            "wage_rate_multiplier": float(self.wage_rate_multiplier),
            "bill_rate_multiplier": float(self.bill_rate_multiplier),
            "is_billable": self.is_billable,
            "wage_rate": float(self.wage_rate),
            "charge_out_rate": float(self.charge_out_rate),
        }
        if self.salary_term_id is not None:
            updates["salary_term_id"] = self.salary_term_id
            updates["pay_basis"] = "salary"
        return updates


def resolve_labour_subtype(
    *, staff: WageBearingStaff, explicit: LabourSubtype | None
) -> LabourSubtype:
    """Resolve the line's labour subtype: the explicit one, else the worker's default."""
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
    """Read the job's charge-out rate for a labour subtype; fail early if unset."""
    try:
        rate = JobLabourRate.objects.get(job=job, labour_subtype=labour_subtype)
    except JobLabourRate.DoesNotExist as exc:
        raise ValidationError(
            f"Job {job.id} has no labour rate for subtype {labour_subtype.name}."
        ) from exc
    return rate.charge_out_rate


def staff_wage_rate(
    staff: WageBearingStaff,
    override: Decimal | None = None,
    *,
    salary_term: StaffPayrollTerm | None = None,
) -> Decimal:
    """Return the hourly cost rate to price a staff member's time at; fail early if unset.

    No implicit global-default or zero-cost fallback is allowed (ADR 0015): the
    costing pipeline substituted ``CompanyDefaults.wage_rate`` and the workshop
    pipeline costed the time at 0.00, so an unconfigured staff member silently
    produced wrong job costs instead of an obvious error. The message names the
    staff member so the fix is a single edit on their record (ADR 0038).

    Opus: Takes the already-resolved salary term rather than a date to resolve one
    from: its only caller needs the term itself as well, and looking it up here
    too made one condition cost two queries and two different messages.
    """
    if staff.pay_basis == "salary" and override is None:
        if salary_term is None:
            raise ValidationError(
                f"Salaried time for {staff.get_display_full_name()} cannot be costed "
                "without their Xero payroll terms."
            )
        return salary_cost_rate(salary_term)
    wage_rate = override if override is not None else staff.wage_rate
    if not wage_rate:
        raise ValidationError(
            f"Wage rate is not configured for staff {staff.get_display_full_name()} "
            f"({staff.id}); set their base wage rate before booking time."
        )
    return wage_rate


def price_time_entry(  # noqa: PLR0913 -- the canonical pipeline's independent pricing inputs
    *,
    job: Job,
    staff: WageBearingStaff,
    meta: dict[str, object],
    labour_subtype: LabourSubtype | None = None,
    wage_rate_override: Decimal | None = None,
    pay_item_override: PayItem | None = None,
) -> TimeEntryPricing:
    """Price one time entry — the single rate-resolution path for the whole app.

    ``meta`` supplies the required ``wage_rate_multiplier`` plus the
    optional ``bill_rate_multiplier``/``is_billable`` billing intent. Leave
    jobs override both multipliers: leave is paid at 1x (0x when unpaid) and is
    never billable.
    """
    raw_multiplier = rate_from_meta(meta, "wage_rate_multiplier")
    if raw_multiplier is None:
        raise ValidationError(
            "Rate multiplier must be provided when creating a new timesheet entry."
        )

    salary_term: StaffPayrollTerm | None = None
    if staff.pay_basis == "salary":
        raw_date = meta.get("date")
        try:
            target_date = date.fromisoformat(str(raw_date))
        except (TypeError, ValueError) as exc:
            raise ValidationError("Timesheet metadata must contain an ISO work date.") from exc
        salary_term = salary_term_on(cast("Staff", staff), target_date)

    subtype = resolve_labour_subtype(staff=staff, explicit=labour_subtype)
    wage_rate = staff_wage_rate(staff, wage_rate_override, salary_term=salary_term)
    requested_wage_multiplier = normalize_multiplier(raw_multiplier)
    # Salary hours allocate a fixed cost; they never create 1.5x/2x payroll
    # earnings. Customer billing remains independently selectable below.
    wage_rate_multiplier = (
        DEFAULT_MULTIPLIER if staff.pay_basis == "salary" else requested_wage_multiplier
    )
    pay_item = pay_item_override or resolve_xero_pay_item_for_job(
        job=job, wage_rate_multiplier=wage_rate_multiplier
    )
    if pay_item is None:
        # Opus: A category Xero pays from its own calculation. The hours are still
        # costed at the staff member's ordinary rate — the business incurs the
        # wage — but no Xero object is named, so the line posts nowhere and the
        # day is paid once rather than twice.
        wage_rate_multiplier = DEFAULT_MULTIPLIER
        bill_rate_multiplier = ZERO_MULTIPLIER
    elif not pay_item.xero_id:
        raise ValidationError(f"Xero pay item '{pay_item.name}' has no xero_id.")
    elif is_leave_pay_item(pay_item):
        wage_rate_multiplier = leave_wage_rate_multiplier(pay_item)
        bill_rate_multiplier = ZERO_MULTIPLIER
    else:
        if pay_item_override is not None:
            if pay_item.multiplier is None:
                raise ValidationError(f"Xero earnings rate '{pay_item.name}' has no multiplier.")
            wage_rate_multiplier = normalize_multiplier(pay_item.multiplier)
        bill_rate_multiplier = (
            ZERO_MULTIPLIER
            if pay_item_override is not None
            else get_bill_rate_multiplier(meta, requested_wage_multiplier)
        )

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
        salary_term_id=str(salary_term.id) if salary_term is not None else None,
    )
