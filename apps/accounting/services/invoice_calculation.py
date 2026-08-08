"""Invoice amount calculation: the single source of a job's invoiceable value.

Ported verbatim from v1 (its own home was apps/accounting/services). The
Finish Job balance, invoice push and fully-invoiced recalculation all read
job value from here so the three cannot disagree.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db.models import Sum, prefetch_related_objects
from django.db.models.functions import Coalesce

from apps.accounting.enums import InvoiceStatus
from apps.accounting.models.invoice import Invoice
from apps.job.models import Job

INVOICE_VALID_STATUSES = [
    status for (status, _) in InvoiceStatus.choices if status not in ["VOIDED", "DELETED"]
]


class InvoiceCalculationError(ValueError):
    """Raised when an invoice cannot be calculated."""


@dataclass
class InvoiceCalculationResult:
    """Everything the endpoint reports about how an invoice amount was derived."""

    mode: str
    target_basis: str
    target_total: Decimal
    prior_invoiced_total: Decimal
    requested_percent: Decimal | None = None
    requested_amount: Decimal | None = None
    calculated_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class JobInvoicingBasis:
    """What a job is worth excluding tax, and which cost set says so."""

    basis: str
    target_total: Decimal


def get_job_invoicing_basis(job: Job) -> JobInvoicingBasis:
    """Return the complete value of a job excluding tax.

    The single place a job's value is derived: fixed-price work is worth its
    quote, T&M work its actual revenue limited by any price cap. Everything that
    needs a job's value — invoice calculation, the Finish Job balance,
    ``job_service.get_job_total_value`` — reads it from here, so the three cannot
    disagree about what a job is worth.
    """
    if job.pricing_methodology == "fixed_price":
        return JobInvoicingBasis(
            basis="quote", target_total=Decimal(str(job.latest_quote.total_revenue))
        )

    actual_revenue = Decimal(str(job.latest_actual.total_revenue))
    if job.price_cap is None:
        return JobInvoicingBasis(basis="actual_revenue", target_total=actual_revenue)

    return JobInvoicingBasis(
        basis="actual_revenue",
        target_total=min(actual_revenue, Decimal(str(job.price_cap))),
    )


def get_prior_valid_invoice_total(job: Job) -> Decimal:
    """Sum the job's non-voided, non-deleted invoice totals (excl tax)."""
    return Decimal(
        Invoice.objects.filter(job_id=job.id, status__in=INVOICE_VALID_STATUSES).aggregate(
            total=Coalesce(Sum("total_excl_tax"), Decimal("0"))
        )["total"]
    )


def get_job_for_invoice_calculation(job_id: UUID) -> Job:
    """Load a job with the cost set its value is measured against.

    Only the basis cost set is fetched: loading both eagerly pulls one that is
    never read, which the n+1 guard reports. Its cost lines are prefetched
    because ``total_revenue`` sums them.
    """
    job = Job.objects.select_related("company").get(id=job_id)

    if job.pricing_methodology == "fixed_price":
        prefetch_related_objects([job], "latest_quote__cost_lines")
    else:
        prefetch_related_objects([job], "latest_actual__cost_lines")

    return job


def calculate_invoice_amount(
    job: Job,
    mode: str,
    percent: Decimal | None = None,
    amount: Decimal | None = None,
) -> InvoiceCalculationResult:
    """Derive the amount an invoice in ``mode`` would bill for this job."""
    prior_invoiced = get_prior_valid_invoice_total(job)
    job_basis = get_job_invoicing_basis(job)

    # Which modes are legal is a different question from what the job is worth,
    # so it keeps its own branch; the handlers below are given the value.
    if job.pricing_methodology == "fixed_price":
        return _calculate_fixed_price(job_basis, mode, prior_invoiced, percent, amount)
    return _calculate_time_materials(job_basis, mode, prior_invoiced, percent, amount)


def _calculate_fixed_price(
    job_basis: JobInvoicingBasis,
    mode: str,
    prior_invoiced: Decimal,
    percent: Decimal | None,
    amount: Decimal | None,
) -> InvoiceCalculationResult:
    target_total = job_basis.target_total

    if mode == "invoice_full":
        calculated = target_total - prior_invoiced

    elif mode == "invoice_percent":
        if percent is None:
            raise InvoiceCalculationError("percent is required for invoice_percent mode.")
        pct = Decimal(str(percent))
        calculated = target_total * pct / Decimal("100") - prior_invoiced

    elif mode == "invoice_amount":
        if amount is None:
            raise InvoiceCalculationError("amount is required for invoice_amount mode.")
        calculated = Decimal(str(amount))
        remaining = target_total - prior_invoiced
        if calculated > remaining:
            raise InvoiceCalculationError(
                f"Invoice amount ${calculated:.2f} exceeds remaining "
                f"quote balance of ${remaining:.2f}."
            )

    else:
        raise InvoiceCalculationError(f"Invalid mode '{mode}' for fixed-price job.")

    return InvoiceCalculationResult(
        mode=mode,
        target_basis=job_basis.basis,
        target_total=target_total,
        prior_invoiced_total=prior_invoiced,
        requested_percent=percent,
        requested_amount=amount,
        calculated_amount=_validate_positive(calculated),
    )


def _calculate_time_materials(
    job_basis: JobInvoicingBasis,
    mode: str,
    prior_invoiced: Decimal,
    percent: Decimal | None,
    amount: Decimal | None,
) -> InvoiceCalculationResult:
    target_total = job_basis.target_total

    if mode == "invoice_costs_to_date":
        calculated = target_total - prior_invoiced

    elif mode == "invoice_amount":
        if amount is None:
            raise InvoiceCalculationError("amount is required for invoice_amount mode.")
        calculated = Decimal(str(amount))

    elif mode == "invoice_percent":
        raise InvoiceCalculationError("invoice_percent is not supported for T&M jobs.")

    elif mode == "invoice_full":
        raise InvoiceCalculationError(
            "invoice_full is not supported for T&M jobs. Use invoice_costs_to_date instead."
        )

    else:
        raise InvoiceCalculationError(f"Invalid mode '{mode}' for T&M job.")

    return InvoiceCalculationResult(
        mode=mode,
        target_basis=job_basis.basis,
        target_total=target_total,
        prior_invoiced_total=prior_invoiced,
        requested_percent=percent,
        requested_amount=amount,
        calculated_amount=_validate_positive(calculated),
    )


def _validate_positive(amount: Decimal) -> Decimal:
    if amount <= Decimal("0"):
        raise InvoiceCalculationError(
            f"Calculated invoice amount (${amount:.2f}) must be positive. "
            "The job may already be fully invoiced."
        )
    return amount
