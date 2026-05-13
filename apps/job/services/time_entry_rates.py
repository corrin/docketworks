from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from django.core.exceptions import ValidationError

from apps.workflow.models import XeroPayItem

CENT = Decimal("0.01")
DEFAULT_MULTIPLIER = Decimal("1.00")
ZERO_MULTIPLIER = Decimal("0.00")


def to_decimal(value: Any, *, default: Decimal = DEFAULT_MULTIPLIER) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def normalize_multiplier(
    value: Any, *, default: Decimal = DEFAULT_MULTIPLIER
) -> Decimal:
    return to_decimal(value, default=default).quantize(CENT)


def get_bill_rate_multiplier(
    meta: Mapping[str, object], wage_rate_multiplier: Decimal
) -> Decimal:
    if "bill_rate_multiplier" in meta and meta.get("bill_rate_multiplier") is not None:
        return normalize_multiplier(meta["bill_rate_multiplier"])

    if meta.get("is_billable") is False:
        return ZERO_MULTIPLIER

    return normalize_multiplier(wage_rate_multiplier)


def resolve_xero_pay_item(wage_rate_multiplier: Decimal) -> XeroPayItem:
    normalized = normalize_multiplier(wage_rate_multiplier)
    pay_item = XeroPayItem.get_by_multiplier(normalized)
    if pay_item is None:
        raise ValidationError(
            f"No Xero pay item found for wage_rate_multiplier={normalized}."
        )
    return pay_item


def is_leave_pay_item(pay_item: XeroPayItem | None) -> bool:
    return pay_item is not None and pay_item.uses_leave_api


def leave_wage_rate_multiplier(pay_item: XeroPayItem) -> Decimal:
    if "unpaid" in pay_item.name.lower():
        return ZERO_MULTIPLIER
    return DEFAULT_MULTIPLIER


def resolve_xero_pay_item_for_job(
    *,
    job: Any,
    wage_rate_multiplier: Decimal,
) -> XeroPayItem:
    job_pay_item = getattr(job, "default_xero_pay_item", None)
    if is_leave_pay_item(job_pay_item):
        if not job_pay_item.xero_id:
            raise ValidationError(
                f"Leave job '{job.name}' has Xero pay item "
                f"'{job_pay_item.name}' with no xero_id."
            )
        return job_pay_item
    return resolve_xero_pay_item(wage_rate_multiplier)


def calculate_time_unit_rates(
    *,
    wage_rate: Any,
    charge_out_rate: Any,
    wage_rate_multiplier: Decimal,
    bill_rate_multiplier: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    base_wage_rate = to_decimal(wage_rate, default=Decimal("0")).quantize(CENT)
    base_charge_out_rate = to_decimal(charge_out_rate, default=Decimal("0")).quantize(
        CENT
    )
    wage_multiplier = normalize_multiplier(wage_rate_multiplier)
    bill_multiplier = normalize_multiplier(bill_rate_multiplier)
    unit_cost = (base_wage_rate * wage_multiplier).quantize(CENT)
    unit_rev = (base_charge_out_rate * bill_multiplier).quantize(CENT)
    return unit_cost, unit_rev, base_wage_rate, base_charge_out_rate
