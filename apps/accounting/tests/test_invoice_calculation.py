"""Tests for invoice calculation service."""

import uuid
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.models.invoice import Invoice
from apps.accounting.services.invoice_calculation import (
    InvoiceCalculationError,
    calculate_invoice_amount,
    get_job_for_invoice_calculation,
    get_prior_valid_invoice_total,
)
from apps.client.models import Client
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.testing import BaseTestCase


class TestInvoiceCalculation(BaseTestCase):
    """Tests for calculate_invoice_amount()."""

    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Test Client",
            xero_last_modified=timezone.now(),
        )

    def _create_job(self, pricing_methodology="time_materials"):
        job = Job(
            client=self.client_obj,
            name="Test Job",
            pricing_methodology=pricing_methodology,
        )
        job.save(staff=self.test_staff)
        return job

    def _add_revenue_line(self, cost_set, revenue):
        CostLine.objects.create(
            cost_set=cost_set,
            kind="adjust",
            desc="Test line",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=Decimal(str(revenue)),
            accounting_date=date.today(),
        )

    def _create_invoice(self, job, amount, status="AUTHORISED"):
        return Invoice.objects.create(
            job=job,
            client=self.client_obj,
            xero_id=uuid.uuid4(),
            number=f"INV-{uuid.uuid4().hex[:8]}",
            status=status,
            total_excl_tax=amount,
            tax=Decimal("0.00"),
            total_incl_tax=amount,
            amount_due=Decimal("0.00"),
            date=date.today(),
            xero_last_modified=timezone.now(),
            raw_json={},
        )

    # --- Quoted job: invoice_full ---

    def test_quoted_invoice_full_no_prior(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        result = calculate_invoice_amount(job, mode="invoice_full")
        self.assertEqual(result.calculated_amount, Decimal("5000"))
        self.assertEqual(result.target_basis, "quote")
        self.assertEqual(result.target_total, Decimal("5000"))
        self.assertEqual(result.prior_invoiced_total, Decimal("0"))

    def test_quoted_invoice_full_with_prior(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        self._create_invoice(job, Decimal("3000"))
        result = calculate_invoice_amount(job, mode="invoice_full")
        self.assertEqual(result.calculated_amount, Decimal("2000"))

    def test_quoted_invoice_full_fully_invoiced(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        self._create_invoice(job, Decimal("5000"))
        with self.assertRaises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_full")

    # --- Quoted job: invoice_percent ---

    def test_quoted_invoice_percent_no_prior(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        result = calculate_invoice_amount(
            job, mode="invoice_percent", percent=Decimal("50")
        )
        self.assertEqual(result.calculated_amount, Decimal("2500"))

    def test_quoted_invoice_percent_with_prior(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        self._create_invoice(job, Decimal("1000"))
        result = calculate_invoice_amount(
            job, mode="invoice_percent", percent=Decimal("50")
        )
        self.assertEqual(result.calculated_amount, Decimal("1500"))

    def test_quoted_invoice_percent_missing_percent(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        with self.assertRaises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_percent")

    # --- Quoted job: invoice_amount ---

    def test_quoted_invoice_amount_valid(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        result = calculate_invoice_amount(
            job, mode="invoice_amount", amount=Decimal("2000")
        )
        self.assertEqual(result.calculated_amount, Decimal("2000"))

    def test_quoted_invoice_amount_exceeds_remaining(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        self._create_invoice(job, Decimal("4000"))
        with self.assertRaises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_amount", amount=Decimal("2000"))

    # --- T&M job: invoice_costs_to_date ---

    def test_tm_costs_to_date_no_prior(self):
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("7500"))
        result = calculate_invoice_amount(job, mode="invoice_costs_to_date")
        self.assertEqual(result.calculated_amount, Decimal("7500"))
        self.assertEqual(result.target_basis, "actual_revenue")

    def test_tm_costs_to_date_with_prior(self):
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("7500"))
        self._create_invoice(job, Decimal("2500"))
        result = calculate_invoice_amount(job, mode="invoice_costs_to_date")
        self.assertEqual(result.calculated_amount, Decimal("5000"))

    # --- T&M job: invoice_amount ---

    def test_tm_invoice_amount_valid(self):
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("7500"))
        result = calculate_invoice_amount(
            job, mode="invoice_amount", amount=Decimal("5000")
        )
        self.assertEqual(result.calculated_amount, Decimal("5000"))

    # --- T&M job: invalid modes ---

    def test_tm_invoice_percent_rejected(self):
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("7500"))
        with self.assertRaises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_percent", percent=Decimal("50"))

    # --- Voided/deleted invoices ---

    def test_voided_invoices_excluded_from_prior(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        self._create_invoice(job, Decimal("3000"), status="VOIDED")
        result = calculate_invoice_amount(job, mode="invoice_full")
        self.assertEqual(result.calculated_amount, Decimal("5000"))

    def test_deleted_invoices_excluded_from_prior(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        self._create_invoice(job, Decimal("3000"), status="DELETED")
        result = calculate_invoice_amount(job, mode="invoice_full")
        self.assertEqual(result.calculated_amount, Decimal("5000"))

    # --- Price cap ---

    def test_tm_price_cap_applied(self):
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("10000"))
        job.price_cap = Decimal("8000")
        job.save(staff=self.test_staff, update_fields=["price_cap"])
        result = calculate_invoice_amount(job, mode="invoice_costs_to_date")
        self.assertEqual(result.calculated_amount, Decimal("8000"))

    # --- Negative/zero rejection ---

    def test_zero_invoice_rejected(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("0"))
        with self.assertRaises(InvoiceCalculationError):
            calculate_invoice_amount(job, mode="invoice_full")

    # --- get_prior_valid_invoice_total ---

    def test_prior_total_excludes_voided_deleted(self):
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))
        self._create_invoice(job, Decimal("1000"), status="AUTHORISED")
        self._create_invoice(job, Decimal("500"), status="VOIDED")
        self._create_invoice(job, Decimal("500"), status="DELETED")
        total = get_prior_valid_invoice_total(job)
        self.assertEqual(total, Decimal("1000"))

    def test_preloaded_job_calculates_without_lazy_loading_cost_lines(self):
        """Xero invoice creation preloads CostSet lines before calculation."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("250"))
        self._add_revenue_line(job.latest_actual, Decimal("750"))
        loaded_job = get_job_for_invoice_calculation(job.id)

        with CaptureQueriesContext(connection) as captured:
            result = calculate_invoice_amount(
                loaded_job,
                mode="invoice_costs_to_date",
            )

        cost_line_queries = [
            query["sql"] for query in captured if 'FROM "job_costline"' in query["sql"]
        ]

        self.assertEqual(cost_line_queries, [])
        self.assertEqual(result.target_total, Decimal("1000.000"))
