"""Invoice amount calculation, ported from v1's suite.

Business risk covered: this service is the single source of a job's
invoiceable value — the Finish Job balance, the Xero invoice push and the
fully-invoiced recalculation all read from it. A wrong mode rule or a missed
prior-invoice subtraction double-bills a customer or blocks invoicing a job
that still has value left.
"""

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounting.services.invoice_calculation import (
    InvoiceCalculationError,
    calculate_invoice_amount,
    get_job_for_invoice_calculation,
    get_job_invoicing_basis,
    get_prior_valid_invoice_total,
)
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job, make_material_line
from apps.job.models import Job

pytestmark = pytest.mark.django_db


@pytest.fixture
def company() -> Company:
    return make_company("Invoice Calc Ltd")


def _fixed_price_job(company: Company, staff: Staff, quote_revenue: str) -> Job:
    job = make_job(company, staff, pricing_methodology="fixed_price")
    make_material_line(job, set_kind="quote", rev=quote_revenue, cost="0.00")
    return job


def _tm_job(company: Company, staff: Staff, actual_revenue: str) -> Job:
    job = make_job(company, staff, pricing_methodology="time_materials")
    make_material_line(job, set_kind="actual", rev=actual_revenue, cost="0.00")
    return job


def _add_prior_invoice(job: Job, amount: str, status: str = "AUTHORISED") -> None:
    assert job.company is not None  # every job here is built with a company
    make_invoice(job.company, job=job, status=status, total_excl_tax=Decimal(amount))


class TestFixedPriceInvoiceFull:
    def test_no_prior_invoices_bills_the_whole_quote(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")

        result = calculate_invoice_amount(job, mode="invoice_full")

        assert result.calculated_amount == Decimal("5000")
        assert result.target_basis == "quote"
        assert result.target_total == Decimal("5000")
        assert result.prior_invoiced_total == Decimal("0")

    def test_prior_invoices_are_subtracted(self, company: Company, office_staff: Staff) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")
        _add_prior_invoice(job, "3000.00")

        result = calculate_invoice_amount(job, mode="invoice_full")

        assert result.calculated_amount == Decimal("2000")

    def test_fully_invoiced_job_is_rejected(self, company: Company, office_staff: Staff) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")
        _add_prior_invoice(job, "5000.00")

        with pytest.raises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_full")


class TestFixedPriceInvoicePercent:
    def test_percent_of_quote_no_prior(self, company: Company, office_staff: Staff) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")

        result = calculate_invoice_amount(job, mode="invoice_percent", percent=Decimal("50"))

        assert result.calculated_amount == Decimal("2500")

    def test_prior_invoices_reduce_the_percent_amount(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")
        _add_prior_invoice(job, "1000.00")

        result = calculate_invoice_amount(job, mode="invoice_percent", percent=Decimal("50"))

        assert result.calculated_amount == Decimal("1500")

    def test_missing_percent_is_rejected(self, company: Company, office_staff: Staff) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")

        with pytest.raises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_percent")


class TestFixedPriceInvoiceAmount:
    def test_explicit_amount_within_remaining_quote(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")

        result = calculate_invoice_amount(job, mode="invoice_amount", amount=Decimal("2000"))

        assert result.calculated_amount == Decimal("2000")

    def test_amount_exceeding_remaining_quote_is_rejected(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")
        _add_prior_invoice(job, "4000.00")

        with pytest.raises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_amount", amount=Decimal("2000"))


class TestTimeMaterialsModes:
    def test_costs_to_date_bills_actual_revenue(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _tm_job(company, office_staff, "7500.00")

        result = calculate_invoice_amount(job, mode="invoice_costs_to_date")

        assert result.calculated_amount == Decimal("7500")
        assert result.target_basis == "actual_revenue"

    def test_costs_to_date_subtracts_prior_invoices(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _tm_job(company, office_staff, "7500.00")
        _add_prior_invoice(job, "2500.00")

        result = calculate_invoice_amount(job, mode="invoice_costs_to_date")

        assert result.calculated_amount == Decimal("5000")

    def test_explicit_amount_is_not_capped_by_actuals(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _tm_job(company, office_staff, "7500.00")

        result = calculate_invoice_amount(job, mode="invoice_amount", amount=Decimal("5000"))

        assert result.calculated_amount == Decimal("5000")

    def test_invoice_percent_is_rejected(self, company: Company, office_staff: Staff) -> None:
        job = _tm_job(company, office_staff, "7500.00")

        with pytest.raises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_percent", percent=Decimal("50"))

    def test_invoice_full_is_rejected(self, company: Company, office_staff: Staff) -> None:
        job = _tm_job(company, office_staff, "7500.00")

        with pytest.raises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_full")


class TestPriorInvoiceTotal:
    def test_voided_invoices_do_not_reduce_remaining(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")
        _add_prior_invoice(job, "3000.00", status="VOIDED")

        result = calculate_invoice_amount(job, mode="invoice_full")

        assert result.calculated_amount == Decimal("5000")

    def test_deleted_invoices_do_not_reduce_remaining(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")
        _add_prior_invoice(job, "3000.00", status="DELETED")

        result = calculate_invoice_amount(job, mode="invoice_full")

        assert result.calculated_amount == Decimal("5000")

    def test_total_sums_only_valid_invoices(self, company: Company, office_staff: Staff) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")
        _add_prior_invoice(job, "1000.00", status="AUTHORISED")
        _add_prior_invoice(job, "500.00", status="VOIDED")
        _add_prior_invoice(job, "500.00", status="DELETED")

        assert get_prior_valid_invoice_total(job) == Decimal("1000")


class TestInvoicingBasis:
    def test_fixed_price_basis_is_the_quote(self, company: Company, office_staff: Staff) -> None:
        job = _fixed_price_job(company, office_staff, "5000.00")

        basis = get_job_invoicing_basis(job)

        assert basis.basis == "quote"
        assert basis.target_total == Decimal("5000")

    def test_price_cap_clamps_tm_actual_revenue(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _tm_job(company, office_staff, "10000.00")
        job.price_cap = Decimal("8000")
        job.save(staff=office_staff, update_fields=["price_cap"])

        result = calculate_invoice_amount(job, mode="invoice_costs_to_date")

        assert result.calculated_amount == Decimal("8000")

    def test_price_cap_above_actuals_does_not_inflate(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _tm_job(company, office_staff, "10000.00")
        job.price_cap = Decimal("12000")
        job.save(staff=office_staff, update_fields=["price_cap"])

        basis = get_job_invoicing_basis(job)

        assert basis.target_total == Decimal("10000")


class TestValidation:
    def test_zero_value_invoice_is_rejected(self, company: Company, office_staff: Staff) -> None:
        job = _fixed_price_job(company, office_staff, "0.00")

        with pytest.raises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_full")


class TestPreloadedJob:
    def test_preloaded_job_calculates_without_lazy_loading_cost_lines(
        self, company: Company, office_staff: Staff
    ) -> None:
        """Xero invoice creation preloads CostSet lines before calculation."""
        job = _tm_job(company, office_staff, "250.00")
        make_material_line(job, set_kind="actual", rev="750.00", cost="0.00")
        loaded_job = get_job_for_invoice_calculation(job.id)

        with CaptureQueriesContext(connection) as captured:
            result = calculate_invoice_amount(loaded_job, mode="invoice_costs_to_date")

        cost_line_queries = [
            query["sql"] for query in captured if 'FROM "job_costline"' in query["sql"]
        ]

        assert cost_line_queries == []
        assert result.target_total == Decimal("1000")
