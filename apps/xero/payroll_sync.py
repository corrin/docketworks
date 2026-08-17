"""Payroll reads for the sync engine: pay runs, pay slips, pay items.

The sync subset of v1's 2,727-LOC ``payroll.py``. Calendar and pay-item SETUP
(the reads and writes ``manage.py xero --setup`` needs) lives in
``payroll_setup``; pay-run create/refresh and employee sync remain a recorded
Phase 4 deferral. Fetchers return the raw SDK objects (not dicts) so the sync
system serialises them into ``raw_json`` unchanged.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from xero_python.payrollnz import PayrollNzApi, PayRun, PaySlip

from apps.core.errors import persist_app_error
from apps.xero.auth import get_api_client, get_tenant_id

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.xero.models import XeroPayItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PayRunsForSync:
    """The fetcher result shape the sync loop iterates (v1 used an anonymous object)."""

    pay_runs: list[PayRun] = field(default_factory=list)


@dataclass(frozen=True)
class PaySlipsForSync:
    """As PayRunsForSync, for pay slips."""

    pay_slips: list[PaySlip] = field(default_factory=list)


def _resolve_tenant_id(kwargs: dict[str, Any]) -> str:
    tenant_id = kwargs.get("xero_tenant_id") or get_tenant_id()
    if not tenant_id:
        raise ValueError("No Xero tenant ID configured for payroll sync")
    return str(tenant_id)


def get_pay_runs_for_sync(**kwargs: Any) -> PayRunsForSync:
    """Fetch pay runs from Xero Payroll for sync (raw PayRun objects)."""
    tenant_id = _resolve_tenant_id(kwargs)
    payroll_api = PayrollNzApi(get_api_client())

    logger.info("Fetching Xero pay runs for sync")
    response = payroll_api.get_pay_runs(xero_tenant_id=tenant_id)

    if response and response.pay_runs:
        logger.info("Retrieved %d pay runs for sync", len(response.pay_runs))
        return PayRunsForSync(pay_runs=list(response.pay_runs))
    return PayRunsForSync()


def get_pay_slips_for_run(pay_run_id: str, **kwargs: Any) -> list[PaySlip]:
    """Fetch the pay slips Xero holds for one pay run.

    Its own function because the interesting question is almost always about a
    single run — "what did Xero compute for the week we just posted?" — and
    answering it by fetching every slip in the organisation costs one call per
    pay run to discard all but one. ``get_all_pay_slips_for_sync`` is the sync
    pass and calls this rather than restating the fetch (ADR 0039).
    """
    tenant_id = _resolve_tenant_id(kwargs)
    payroll_api = PayrollNzApi(get_api_client())
    logger.debug("Fetching pay slips for pay run %s", pay_run_id)
    response = payroll_api.get_pay_slips(xero_tenant_id=tenant_id, pay_run_id=pay_run_id)
    if not response or not response.pay_slips:
        return []
    return list(response.pay_slips)


def get_all_pay_slips_for_sync(**kwargs: Any) -> PaySlipsForSync:
    """Fetch ALL pay slips across ALL pay runs (N+1 API calls by design).

    The transform resolves each slip's parent from the XeroPayRun table by
    pay_run_id — nothing is attached to the SDK objects.
    """
    tenant_id = _resolve_tenant_id(kwargs)
    payroll_api = PayrollNzApi(get_api_client())

    logger.info("Fetching all pay runs to gather pay slips")
    pay_runs_response = payroll_api.get_pay_runs(xero_tenant_id=tenant_id)

    if not pay_runs_response or not pay_runs_response.pay_runs:
        logger.info("No pay runs found")
        return PaySlipsForSync()

    all_pay_slips: list[PaySlip] = []
    for pay_run in pay_runs_response.pay_runs:
        all_pay_slips.extend(
            get_pay_slips_for_run(str(pay_run.pay_run_id), xero_tenant_id=tenant_id)
        )

    logger.info("Retrieved %d total pay slips for sync", len(all_pay_slips))
    return PaySlipsForSync(pay_slips=all_pay_slips)


def get_pay_run(pay_run_id: str) -> PayRun | None:
    """Get a single pay run from Xero by ID (None if not found)."""
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_api_client())

    try:
        logger.info("Fetching Xero pay run %s", pay_run_id)
        response = payroll_api.get_pay_run(xero_tenant_id=tenant_id, pay_run_id=pay_run_id)
    except Exception as exc:
        logger.exception("Failed to get Xero pay run %s", pay_run_id)
        persist_app_error(exc)
        raise
    if response and response.pay_run:
        return response.pay_run
    return None


def get_leave_types() -> list[dict[str, Any]]:
    """List Xero Payroll leave types as {id, name} dicts."""
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_api_client())

    try:
        logger.info("Fetching Xero Payroll leave types")
        response = payroll_api.get_leave_types(xero_tenant_id=tenant_id)

        leave_types: list[dict[str, Any]] = []
        if response and response.leave_types:
            leave_types.extend(
                {"id": lt.leave_type_id, "name": lt.name} for lt in response.leave_types
            )
    except Exception as exc:
        logger.exception("Failed to get Xero Payroll leave types")
        persist_app_error(exc)
        raise
    logger.info("Retrieved %d leave types from Xero Payroll", len(leave_types))
    return leave_types


def get_earnings_rates() -> list[dict[str, Any]]:
    """List Xero Payroll earnings rates with their inferred multipliers."""
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_api_client())

    try:
        logger.info("Fetching Xero Payroll earnings rates")
        response = payroll_api.get_earnings_rates(xero_tenant_id=tenant_id)

        earnings_rates: list[dict[str, Any]] = []
        if response and response.earnings_rates:
            for rate in response.earnings_rates:
                # rate_type ∈ {RatePerUnit, MultipleOfOrdinaryEarningsRate, FixedAmount}
                multiplier: float | None = None
                if rate.rate_type == "MultipleOfOrdinaryEarningsRate":
                    multiplier = rate.multiple_of_ordinary_earnings_rate
                elif rate.rate_type == "RatePerUnit":
                    # Ordinary time is rate-per-unit with an implicit 1.0x multiplier
                    multiplier = 1.0

                earnings_rates.append(
                    {
                        "id": rate.earnings_rate_id,
                        "name": rate.name,
                        "earnings_type": rate.earnings_type,
                        "rate_type": rate.rate_type,
                        "type_of_units": rate.type_of_units,
                        "multiplier": multiplier,
                        "expense_account_id": (
                            str(rate.expense_account_id) if rate.expense_account_id else None
                        ),
                    }
                )
    except Exception as exc:
        logger.exception("Failed to get Xero Payroll earnings rates")
        persist_app_error(exc)
        raise
    logger.info("Retrieved %d earnings rates from Xero Payroll", len(earnings_rates))
    return earnings_rates


def pay_items_needing_relink(tenant_id: str) -> "QuerySet[XeroPayItem]":
    """Referenced pay items that are not linked to the connected organisation.

    Referenced means a ``Job.default_xero_pay_item`` or a
    ``CostLine.xero_pay_item`` points at the row: an unreferenced item with no
    ``xero_id`` is a backup remnant nothing posts through, so counting it would
    make the seed demand a re-link that can never complete.

    "Linked to us" is ``xero_id`` set AND the tenant ours, the same pairing
    ``sync_xero_pay_items`` writes — an id with a foreign tenant is a
    production id the target org has never held.
    """
    # Call-time imports, as in sync_xero_pay_items below: this module is
    # imported by the sync engine before Django's app registry is ready in some
    # tool contexts.
    from apps.job.models import CostLine, Job  # noqa: PLC0415
    from apps.xero.models import XeroPayItem  # noqa: PLC0415

    referenced = set(
        Job.objects.filter(default_xero_pay_item_id__isnull=False).values_list(
            "default_xero_pay_item_id", flat=True
        )
    ) | set(
        CostLine.objects.filter(xero_pay_item_id__isnull=False).values_list(
            "xero_pay_item_id", flat=True
        )
    )
    return XeroPayItem.objects.filter(id__in=referenced).exclude(
        xero_id__isnull=False, xero_tenant_id=tenant_id
    )


def sync_xero_pay_items() -> dict[str, Any]:
    """Sync XeroPayItem rows from Xero leave types and earnings rates.

    Returns a dict with created/updated counts and a top-level
    ``records_updated`` total so the sync orchestrator doesn't have to know
    the result shape.
    """
    # Call-time imports: this module is imported by the sync engine before
    # Django's app registry is ready in some tool contexts.
    from django.utils import timezone  # noqa: PLC0415

    from apps.xero.models import XeroPayItem  # noqa: PLC0415

    tenant_id = get_tenant_id()

    results: dict[str, Any] = {
        "leave_types": {"created": 0, "updated": 0},
        "earnings_rates": {"created": 0, "updated": 0},
    }

    # Fetch all data upfront - fail fast if API errors
    logger.info("Fetching Xero Leave Types and Earnings Rates")
    leave_types = get_leave_types()
    earnings_rates = get_earnings_rates()

    logger.info("Syncing %d leave types to XeroPayItem", len(leave_types))
    for lt in leave_types:
        # Multiplier inferred from the leave-type name: unpaid → 0 (we don't
        # pay them), annual → 0 (accrual has already set the money aside),
        # everything else 1.
        name_lower = str(lt["name"]).lower()
        if "unpaid" in name_lower or "annual" in name_lower:
            leave_multiplier = Decimal("0.00")
        else:
            leave_multiplier = Decimal("1.00")

        _pay_item, created = XeroPayItem.objects.update_or_create(
            name=lt["name"],
            uses_leave_api=True,
            defaults={
                "xero_id": str(lt["id"]),
                "xero_tenant_id": tenant_id,
                "multiplier": leave_multiplier,
                "xero_last_synced": timezone.now(),
            },
        )
        if created:
            results["leave_types"]["created"] += 1
            logger.info("Created XeroPayItem: %s (leave type)", lt["name"])
        else:
            results["leave_types"]["updated"] += 1

    logger.info("Syncing %d earnings rates to XeroPayItem", len(earnings_rates))
    for rate in earnings_rates:
        raw_multiplier = rate.get("multiplier")
        multiplier = Decimal(str(raw_multiplier)) if raw_multiplier is not None else None

        _pay_item, created = XeroPayItem.objects.update_or_create(
            name=rate["name"],
            uses_leave_api=False,
            defaults={
                "xero_id": str(rate["id"]),
                "xero_tenant_id": tenant_id,
                "multiplier": multiplier,
                "xero_last_synced": timezone.now(),
            },
        )
        if created:
            results["earnings_rates"]["created"] += 1
            logger.info("Created XeroPayItem: %s (multiplier=%s)", rate["name"], multiplier)
        else:
            results["earnings_rates"]["updated"] += 1

    logger.info(
        "XeroPayItem sync complete: %d leave types created, %d updated; "
        "%d earnings rates created, %d updated.",
        results["leave_types"]["created"],
        results["leave_types"]["updated"],
        results["earnings_rates"]["created"],
        results["earnings_rates"]["updated"],
    )

    # The same queryset the seed measures with, so "the sync is incomplete" and
    # "the seed has not converged" cannot disagree. It is already restricted to
    # REFERENCED items, so a non-empty result is by construction a real
    # referential break — the old "any job or cost line affected?" re-check was
    # the second half of a predicate stated twice.
    from apps.job.models import CostLine, Job  # noqa: PLC0415

    unrelinked_ids = set(pay_items_needing_relink(tenant_id).values_list("id", flat=True))
    if unrelinked_ids:
        jobs_affected = Job.objects.filter(default_xero_pay_item_id__in=unrelinked_ids).count()
        costlines_affected = CostLine.objects.filter(xero_pay_item_id__in=unrelinked_ids).count()
        orphaned_names = sorted(
            XeroPayItem.objects.filter(id__in=unrelinked_ids).values_list("name", flat=True)
        )
        raise ValueError(
            f"XeroPayItem sync incomplete: {jobs_affected} jobs and "
            f"{costlines_affected} costlines reference pay items not linked to "
            f"this organisation. These exist in the backup but were not matched "
            f"in Xero: {orphaned_names}"
        )

    results["records_updated"] = (
        results["leave_types"]["created"]
        + results["leave_types"]["updated"]
        + results["earnings_rates"]["created"]
        + results["earnings_rates"]["updated"]
    )
    return results
