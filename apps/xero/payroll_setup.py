"""Payroll calendar and pay-item setup against a target Xero org.

The write half of payroll configuration, split from ``payroll_sync`` (which
mirrors Xero into local rows and never writes to Xero). Used by
``manage.py xero --setup``:

- a demo/dev org gets its calendar and pay items CREATED (they vanish on a
  Xero demo-tenant reset);
- production gets them VALIDATED — a setup run must never invent payroll
  configuration in a live org.

Employee writes remain a Phase 4 deferral (see
``apps/timesheet/services/payroll_employee_sync.py``); nothing here touches
employees.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.utils.timezone import localdate
from xero_python.payrollnz import (
    CalendarType,
    EarningsRate,
    LeaveType,
    PayrollNzApi,
    PayRunCalendar,
)

from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.payroll_sync import get_earnings_rates, get_leave_types

logger = logging.getLogger(__name__)

# Xero's demo data seeds an unpaid leave type under this exact name; every
# other leave type we create is paid.
UNPAID_LEAVE_NAME = "Unpaid Leave"

# A freshly restored dev/demo org has full timesheet data for recent COMPLETE
# weeks and little for the current in-progress one, so the first postable pay
# run should land on a week that actually has data.
CALENDAR_ANCHOR_WEEKS_BACK = 4
# Payment date must fall after period end (period_start + 6); +9 is the
# "Wednesday after period end" convention the pay-run creation path uses.
CALENDAR_PAYMENT_OFFSET_DAYS = 9


@dataclass(frozen=True)
class PayrollCalendar:
    """A Xero pay run calendar.

    A dataclass rather than v1's dict: the fields are read by anchor checks
    and id lookups where a typo'd key would silently mean "not configured"
    (ADR 0028).
    """

    id: str
    name: str
    calendar_type: str
    period_start_date: date
    period_end_date: date
    payment_date: date


@dataclass(frozen=True)
class DemoPayItemSetup:
    """What ``ensure_demo_pay_items_exist`` created in the target org."""

    calendar_created: str | None
    leave_types_created: list[str]
    earnings_rates_created: list[str]


def _required(value: object, field: str, calendar_name: object) -> Any:
    """Return an SDK field, refusing the None the stubs allow.

    Returns ``Any`` because one helper narrows six differently-typed SDK
    fields; each call site immediately binds the result to a typed dataclass
    field, so the looseness never escapes this module.

    Malformed payroll data is fixed at the source, never defaulted around
    (ADR 0015): a calendar with no period start cannot be anchor-checked, and
    a fabricated one would pass the check and break payroll posting later.
    """
    if value is None:
        raise ValueError(f"Xero payroll calendar {calendar_name!r} is missing {field}")
    return value


def get_payroll_calendars() -> list[PayrollCalendar]:
    """List the pay run calendars configured in the connected Xero org."""
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_api_client())

    logger.info("Fetching Xero Payroll calendars")
    response = payroll_api.get_pay_run_calendars(xero_tenant_id=tenant_id)

    calendars: list[PayrollCalendar] = []
    for cal in response.pay_run_calendars or []:
        calendar_type = _required(cal.calendar_type, "calendar_type", cal.name)
        calendars.append(
            PayrollCalendar(
                id=str(_required(cal.payroll_calendar_id, "payroll_calendar_id", cal.name)),
                name=str(_required(cal.name, "name", cal.name)),
                calendar_type=str(calendar_type.value),
                period_start_date=_required(cal.period_start_date, "period_start_date", cal.name),
                period_end_date=_required(cal.period_end_date, "period_end_date", cal.name),
                payment_date=_required(cal.payment_date, "payment_date", cal.name),
            )
        )

    logger.info("Retrieved %d payroll calendars from Xero", len(calendars))
    return calendars


def _create_demo_calendar(payroll_api: PayrollNzApi, calendar_name: str, tenant_id: str) -> None:
    """Create the weekly calendar and verify Xero honoured the Monday anchor."""
    today = localdate()
    period_start = today - timedelta(days=today.weekday(), weeks=CALENDAR_ANCHOR_WEEKS_BACK)

    logger.info("Payroll calendar %r not found - creating it", calendar_name)
    payroll_api.create_pay_run_calendar(
        xero_tenant_id=tenant_id,
        pay_run_calendar=PayRunCalendar(
            name=calendar_name,
            calendar_type=CalendarType.WEEKLY,
            period_start_date=period_start,
            payment_date=period_start + timedelta(days=CALENDAR_PAYMENT_OFFSET_DAYS),
        ),
    )

    # Confirm Xero honoured the Monday anchor. If it didn't, payroll posting
    # (which hard-requires period_start.weekday() == 0) breaks weeks later —
    # fail the setup run now instead.
    created = next((c for c in get_payroll_calendars() if c.name == calendar_name), None)
    if created is None or created.period_start_date.weekday() != 0:
        got = (
            created.period_start_date.strftime("%A %Y-%m-%d")
            if created
            else "<calendar not found after creation>"
        )
        raise ValueError(
            f"Created payroll calendar {calendar_name!r} but its period starts on "
            f"{got}, not a Monday. Docketworks requires a Monday-start weekly calendar."
        )
    logger.info("Created payroll calendar %s", calendar_name)


def ensure_demo_pay_items_exist(calendar_name: str, tenant_id: str) -> DemoPayItemSetup:
    """Create the calendar and pay items a demo org is missing.

    Demo-only: the target org is expected to have been reset, dropping
    configuration the restored database still references. Production takes
    ``validate_production_pay_items`` instead.
    """
    # Call-time import: this module is imported by a management command before
    # the app registry is necessarily ready.
    from apps.xero.models import XeroPayItem  # noqa: PLC0415

    if not calendar_name:
        raise ValueError(
            "xero_payroll_calendar_name is required before Xero setup can create "
            "the demo payroll calendar."
        )

    payroll_api = PayrollNzApi(get_api_client())

    calendar_created: str | None = None
    if not any(c.name == calendar_name for c in get_payroll_calendars()):
        _create_demo_calendar(payroll_api, calendar_name, tenant_id)
        calendar_created = calendar_name

    # Compare local pay items (from the prod backup) against the destination
    # org BY NAME and create anything missing. By name rather than
    # `xero_id IS NULL` so this works on the first run, before the seed's
    # clear phase has nulled the stale prod xero_ids.
    pay_items = list(XeroPayItem.objects.all())
    if not pay_items:
        return DemoPayItemSetup(
            calendar_created=calendar_created, leave_types_created=[], earnings_rates_created=[]
        )

    all_rates = get_earnings_rates()
    existing_rates = {rate["name"] for rate in all_rates}
    existing_leave = {leave["name"] for leave in get_leave_types()}

    # Borrow the expense account from an existing rate: Xero requires one on
    # every earnings rate, and the demo org's chart of accounts is not ours
    # to pick from.
    expense_account_id = next(
        (rate["expense_account_id"] for rate in all_rates if rate["expense_account_id"]), None
    )
    if not expense_account_id:
        raise ValueError(
            "Cannot create demo earnings rates: no existing rate has an expense_account_id."
        )

    leave_types_created: list[str] = []
    earnings_rates_created: list[str] = []
    for item in pay_items:
        if item.uses_leave_api:
            if item.name in existing_leave:
                continue
            logger.info("Leave type %r not found - creating it", item.name)
            payroll_api.create_leave_type(
                xero_tenant_id=tenant_id,
                leave_type=LeaveType(
                    name=item.name,
                    is_paid_leave=item.name != UNPAID_LEAVE_NAME,
                    show_on_payslip=True,
                ),
            )
            leave_types_created.append(item.name)
        else:
            if item.name in existing_rates:
                continue
            logger.info("Earnings rate %r not found - creating it", item.name)
            multiplier = float(item.multiplier) if item.multiplier is not None else 1.0
            payroll_api.create_earnings_rate(
                xero_tenant_id=tenant_id,
                earnings_rate=EarningsRate(
                    name=item.name,
                    earnings_type="OtherGrossEarnings",
                    rate_type="MultipleOfOrdinaryEarningsRate",
                    multiple_of_ordinary_earnings_rate=multiplier,
                    type_of_units="Hours",
                    expense_account_id=expense_account_id,
                ),
            )
            earnings_rates_created.append(item.name)

    return DemoPayItemSetup(
        calendar_created=calendar_created,
        leave_types_created=leave_types_created,
        earnings_rates_created=earnings_rates_created,
    )


def validate_production_pay_items(calendar_name: str) -> None:
    """Require the production payroll configuration; never create Xero data."""
    # Call-time import, as ensure_demo_pay_items_exist explains.
    from apps.xero.models import XeroPayItem  # noqa: PLC0415

    if not calendar_name:
        raise ValueError("Production requires xero_payroll_calendar_name.")

    if not any(c.name == calendar_name for c in get_payroll_calendars()):
        raise ValueError(
            f"Payroll calendar '{calendar_name}' does not exist in the production Xero tenant."
        )

    pay_items = list(XeroPayItem.objects.all())
    if not pay_items:
        raise ValueError("No required XeroPayItem records are configured locally.")

    earnings_names = {rate["name"] for rate in get_earnings_rates()}
    leave_names = {leave["name"] for leave in get_leave_types()}
    missing = [
        item.name
        for item in pay_items
        if item.name not in (leave_names if item.uses_leave_api else earnings_names)
    ]
    if missing:
        raise ValueError(
            "Production Xero is missing required pay items: " + ", ".join(sorted(missing))
        )
