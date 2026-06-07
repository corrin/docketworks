from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db.models import Sum, prefetch_related_objects
from django.db.models.functions import Coalesce

from apps.accounting.enums import InvoiceStatus
from apps.accounting.models.invoice import Invoice
from apps.job.models import Job

INVOICE_VALID_STATUSES = [
    status
    for (status, _) in InvoiceStatus.choices
    if status not in ["VOIDED", "DELETED"]
]


class InvoiceCalculationError(ValueError):
    """Raised when an invoice cannot be calculated."""


@dataclass
class InvoiceCalculationResult:
    mode: str
    target_basis: str
    target_total: Decimal
    prior_invoiced_total: Decimal
    requested_percent: Decimal | None = None
    requested_amount: Decimal | None = None
    calculated_amount: Decimal = Decimal("0")


def get_prior_valid_invoice_total(job: Job) -> Decimal:
    return Decimal(
        Invoice.objects.filter(
            job_id=job.id, status__in=INVOICE_VALID_STATUSES
        ).aggregate(total=Coalesce(Sum("total_excl_tax"), Decimal("0")))["total"]
    )


def get_job_for_invoice_calculation(job_id: UUID) -> Job:
    job = Job.objects.select_related("client", "latest_quote", "latest_actual").get(
        id=job_id
    )

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
    prior_invoiced = get_prior_valid_invoice_total(job)

    if job.pricing_methodology == "fixed_price":
        return _calculate_fixed_price(job, mode, prior_invoiced, percent, amount)
    else:
        return _calculate_time_materials(job, mode, prior_invoiced, percent, amount)


def _calculate_fixed_price(
    job: Job,
    mode: str,
    prior_invoiced: Decimal,
    percent: Decimal | None,
    amount: Decimal | None,
) -> InvoiceCalculationResult:
    quote = job.latest_quote
    if not quote:
        raise InvoiceCalculationError(
            "Fixed-price job has no quote to invoice against."
        )
    target_total = Decimal(str(quote.total_revenue))
    target_basis = "quote"

    if mode == "invoice_full":
        calculated = target_total - prior_invoiced

    elif mode == "invoice_percent":
        if percent is None:
            raise InvoiceCalculationError(
                "percent is required for invoice_percent mode."
            )
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
        target_basis=target_basis,
        target_total=target_total,
        prior_invoiced_total=prior_invoiced,
        requested_percent=percent,
        requested_amount=amount,
        calculated_amount=_validate_positive(calculated),
    )


def _calculate_time_materials(
    job: Job,
    mode: str,
    prior_invoiced: Decimal,
    percent: Decimal | None,
    amount: Decimal | None,
) -> InvoiceCalculationResult:
    actual = job.latest_actual
    if not actual:
        raise InvoiceCalculationError(
            "T&M job has no actual cost set to invoice against."
        )
    target_total = Decimal(str(actual.total_revenue))

    if job.price_cap is not None:
        target_total = min(target_total, Decimal(str(job.price_cap)))

    target_basis = "actual_revenue"

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
            "invoice_full is not supported for T&M jobs. "
            "Use invoice_costs_to_date instead."
        )

    else:
        raise InvoiceCalculationError(f"Invalid mode '{mode}' for T&M job.")

    return InvoiceCalculationResult(
        mode=mode,
        target_basis=target_basis,
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
