"""Authoritative customer balance for the Finish Job workspace.

Answers the counter question — what does this customer need to pay, including
tax — as decimal currency values, so the frontend only formats what it is
given (ADR 0046).

Adds nothing but the tax and outstanding-balance arithmetic: the job's value,
its price cap and the valid-invoice statuses all come from
``invoice_calculation``, so the amount a user can invoice and the amount they
are shown cannot drift apart.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.accounting.models import Invoice
from apps.accounting.services.invoice_calculation import (
    INVOICE_VALID_STATUSES,
    get_job_invoicing_basis,
    get_prior_valid_invoice_total,
)
from apps.core.models import CompanyDefaults
from apps.job.models import Job

CENT = Decimal("0.01")


@dataclass(frozen=True)
class FinishJobSummary:
    """Every currency value the Finish Job workspace displays."""

    job_value_excl_gst: Decimal
    valid_invoiced_excl_gst: Decimal
    outstanding_invoiced_incl_gst: Decimal
    remaining_to_invoice_excl_gst: Decimal
    remaining_gst: Decimal
    remaining_to_invoice_incl_gst: Decimal
    total_to_pay_incl_gst: Decimal
    over_invoiced_excl_gst: Decimal


def get_outstanding_invoiced_incl_tax(job: Job) -> Decimal:
    """Sum what Xero still expects to be paid on this job's valid invoices."""
    return Decimal(
        Invoice.objects.filter(job_id=job.id, status__in=INVOICE_VALID_STATUSES).aggregate(
            total=Coalesce(Sum("amount_due"), Decimal("0"))
        )["total"]
    )


def build_finish_job_summary(job: Job) -> FinishJobSummary:
    """Derive the full balance from the invoicing basis and the invoice ledger."""
    job_value = get_job_invoicing_basis(job).target_total.quantize(CENT, rounding=ROUND_HALF_UP)
    invoiced = get_prior_valid_invoice_total(job)
    outstanding = get_outstanding_invoiced_incl_tax(job)

    # A job invoiced beyond its value has nothing left to invoice; the excess
    # is reported separately for resolution in Xero rather than netted off,
    # which would hide it behind a smaller remaining balance.
    remaining_excl = max(job_value - invoiced, Decimal("0"))
    over_invoiced = max(invoiced - job_value, Decimal("0"))

    gst_rate = CompanyDefaults.get_solo().gst_rate
    remaining_gst = (remaining_excl * gst_rate).quantize(CENT, rounding=ROUND_HALF_UP)
    remaining_incl = remaining_excl + remaining_gst

    return FinishJobSummary(
        job_value_excl_gst=job_value,
        valid_invoiced_excl_gst=invoiced,
        outstanding_invoiced_incl_gst=outstanding,
        remaining_to_invoice_excl_gst=remaining_excl,
        remaining_gst=remaining_gst,
        remaining_to_invoice_incl_gst=remaining_incl,
        total_to_pay_incl_gst=outstanding + remaining_incl,
        over_invoiced_excl_gst=over_invoiced,
    )
