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
from django.utils.translation import gettext

from apps.accounting.enums import InvoiceStatus
from apps.accounting.models.invoice import Invoice
from apps.job.models import Job

# The third definition of a valid invoice, kept as-is: WIP counts DRAFT, the sales
# forecast excludes it, and this derives everything but VOIDED and DELETED from
# the enum. Unifying the three is an owner decision nobody has asked for.
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
            raise InvoiceCalculationError(gettext("percent is required for invoice_percent mode."))
        pct = Decimal(str(percent))
        if pct > Decimal("100"):
            raise InvoiceCalculationError(
                gettext("percent must be 100 or less, got %(percent)s.") % {"percent": pct}
            )
        calculated = target_total * pct / Decimal("100") - prior_invoiced

    elif mode == "invoice_amount":
        if amount is None:
            raise InvoiceCalculationError(gettext("amount is required for invoice_amount mode."))
        calculated = Decimal(str(amount))
        remaining = target_total - prior_invoiced
        if calculated > remaining:
            raise InvoiceCalculationError(
                gettext(
                    "Invoice amount $%(amount)s exceeds remaining quote balance of $%(remaining)s."
                )
                % {"amount": f"{calculated:.2f}", "remaining": f"{remaining:.2f}"}
            )

    else:
        raise InvoiceCalculationError(
            gettext("Invalid mode '%(mode)s' for fixed-price job.") % {"mode": mode}
        )

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
            raise InvoiceCalculationError(gettext("amount is required for invoice_amount mode."))
        calculated = Decimal(str(amount))

    elif mode == "invoice_percent":
        raise InvoiceCalculationError(gettext("invoice_percent is not supported for T&M jobs."))

    elif mode == "invoice_full":
        raise InvoiceCalculationError(
            gettext(
                "invoice_full is not supported for T&M jobs. Use invoice_costs_to_date instead."
            )
        )

    else:
        raise InvoiceCalculationError(
            gettext("Invalid mode '%(mode)s' for T&M job.") % {"mode": mode}
        )

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
            gettext(
                "Calculated invoice amount ($%(amount)s) must be positive. "
                "The job may already be fully invoiced."
            )
            % {"amount": f"{amount:.2f}"}
        )
    return amount
