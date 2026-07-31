"""Authoritative customer balance for the Finish Job workspace.

Answers the counter question — what does this customer need to pay, including
tax — as a single set of decimal currency values. Every figure is computed here
so the frontend only formats what it is given (ADR 0020).

The job value, price-cap behaviour and valid-invoice statuses come from
``invoice_calculation``; this module adds only the tax and outstanding-balance
arithmetic on top of them, so a change to the invoicing basis moves both the
invoice a user can create and the balance they are shown.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from django.db.models import Sum, prefetch_related_objects
from django.db.models.functions import Coalesce

from apps.accounting.models.invoice import Invoice
from apps.accounting.services.invoice_calculation import (
    INVOICE_VALID_STATUSES,
    get_job_value_basis,
    get_job_value_excl_tax,
    get_prior_valid_invoice_total,
)
from apps.job.models import Job
from apps.workflow.models import CompanyDefaults

CENT = Decimal("0.01")


@dataclass(frozen=True)
class FinishJobSummary:
    """Every currency value the Finish Job workspace displays.

    ``basis`` names the cost set the job value is measured against ("quote" for
    fixed-price work, "actual_revenue" for T&M) so the UI can label the figure
    without inferring it from the pricing methodology.
    """

    basis: str
    job_value_excl_gst: Decimal
    valid_invoiced_excl_gst: Decimal
    outstanding_invoiced_incl_gst: Decimal
    remaining_to_invoice_excl_gst: Decimal
    remaining_gst: Decimal
    remaining_to_invoice_incl_gst: Decimal
    total_to_pay_incl_gst: Decimal
    over_invoiced_excl_gst: Decimal


def get_outstanding_invoiced_incl_tax(job: Job) -> Decimal:
    """What Xero still expects to be paid on this job's valid invoices."""
    return Decimal(
        Invoice.objects.filter(
            job_id=job.id, status__in=INVOICE_VALID_STATUSES
        ).aggregate(total=Coalesce(Sum("amount_due"), Decimal("0")))["total"]
    )


def get_job_for_finish_summary(job_id: UUID) -> Job:
    """Load a job with the cost set its value is measured against.

    Only the basis cost set is loaded, and its cost lines are prefetched because
    the job value sums them. Fetching both cost sets would eagerly load one the
    summary never reads; fetching neither would cost a query per cost line.
    """
    job = Job.objects.get(id=job_id)

    if job.pricing_methodology == "fixed_price":
        prefetch_related_objects([job], "latest_quote__cost_lines")
    else:
        prefetch_related_objects([job], "latest_actual__cost_lines")

    return job


def build_finish_job_summary(job: Job) -> FinishJobSummary:
    job_value = _as_currency(get_job_value_excl_tax(job))
    invoiced = _as_currency(get_prior_valid_invoice_total(job))
    outstanding = _as_currency(get_outstanding_invoiced_incl_tax(job))

    # A job invoiced beyond its value has nothing left to invoice; the excess is
    # reported separately for resolution in Xero rather than netted off, which
    # would hide it behind a smaller remaining balance.
    remaining_excl = max(job_value - invoiced, Decimal("0"))
    over_invoiced = max(invoiced - job_value, Decimal("0"))

    gst_rate = CompanyDefaults.get_solo().gst_rate
    remaining_gst = (remaining_excl * gst_rate).quantize(CENT, rounding=ROUND_HALF_UP)
    remaining_incl = remaining_excl + remaining_gst

    return FinishJobSummary(
        basis=get_job_value_basis(job),
        job_value_excl_gst=job_value,
        valid_invoiced_excl_gst=invoiced,
        outstanding_invoiced_incl_gst=outstanding,
        remaining_to_invoice_excl_gst=remaining_excl,
        remaining_gst=remaining_gst,
        remaining_to_invoice_incl_gst=remaining_incl,
        total_to_pay_incl_gst=outstanding + remaining_incl,
        over_invoiced_excl_gst=over_invoiced,
    )


def _as_currency(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)
