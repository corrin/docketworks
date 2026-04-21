"""Tests for job invoicing state logic in recalculate_job_invoicing_state()."""

import uuid
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.accounting.models.invoice import Invoice
from apps.client.models import Client
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services.job_service import recalculate_job_invoicing_state
from apps.testing import BaseTestCase


class TestRecalculateJobInvoicingState(BaseTestCase):
    """Tests for recalculate_job_invoicing_state()."""

    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Test Client",
            xero_last_modified=timezone.now(),
        )

    def _create_job(self, pricing_methodology="time_materials"):
        """Create a job. Job.save() auto-creates CostSets (actual, quote, estimate)."""
        job = Job(
            client=self.client_obj,
            name="Test Job",
            pricing_methodology=pricing_methodology,
        )
        job.save(staff=self.test_staff)
        return job

    def _add_revenue_line(self, cost_set, revenue):
        """Add a CostLine with the given revenue to an existing CostSet."""
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
        """Create an invoice for the given job."""
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

    # --- T&M tests ---

    def test_tm_fully_invoiced_when_invoiced_equals_actual(self):
        """T&M job is fully invoiced when invoiced amount equals actual revenue."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("1000.00"))
        self._create_invoice(job, Decimal("1000.00"))

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertTrue(job.fully_invoiced)

    def test_tm_fully_invoiced_when_invoiced_exceeds_actual(self):
        """T&M job is fully invoiced when invoiced amount exceeds actual revenue."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("1000.00"))
        self._create_invoice(job, Decimal("1200.00"))

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertTrue(job.fully_invoiced)

    def test_tm_not_fully_invoiced_when_invoiced_less_than_actual(self):
        """T&M job is not fully invoiced when invoiced less than actual revenue."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("1000.00"))
        self._create_invoice(job, Decimal("500.00"))

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertFalse(job.fully_invoiced)

    # --- Fixed-price tests ---

    def test_fixed_price_fully_invoiced_when_invoiced_equals_quote(self):
        """Fixed-price job is fully invoiced when invoiced matches quote revenue."""
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_actual, Decimal("800.00"))
        self._add_revenue_line(job.latest_quote, Decimal("1000.00"))
        self._create_invoice(job, Decimal("1000.00"))

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertTrue(job.fully_invoiced)

    def test_fixed_price_not_fully_invoiced_even_if_exceeds_actual(self):
        """Fixed-price job is NOT fully invoiced when invoiced >= actual but < quote."""
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_actual, Decimal("800.00"))
        self._add_revenue_line(job.latest_quote, Decimal("1200.00"))

        # Invoiced matches actual (800) but is less than quote (1200)
        self._create_invoice(job, Decimal("800.00"))

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertFalse(job.fully_invoiced)

    def test_fixed_price_without_quote_falls_back_to_actual(self):
        """Fixed-price job without a quote falls back to actual revenue."""
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_actual, Decimal("1000.00"))
        # Clear the auto-created latest_quote
        job.latest_quote = None
        job.save(staff=self.test_staff, update_fields=["latest_quote"])

        self._create_invoice(job, Decimal("1000.00"))

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertTrue(job.fully_invoiced)

    # --- Edge cases ---

    def test_not_fully_invoiced_with_no_invoices(self):
        """Job with no invoices is not fully invoiced."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("1000.00"))

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertFalse(job.fully_invoiced)

    def test_voided_invoices_excluded(self):
        """Voided invoices should not count toward total invoiced."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("1000.00"))
        self._create_invoice(job, Decimal("1000.00"), status="VOIDED")

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertFalse(job.fully_invoiced)

    def test_deleted_invoices_excluded(self):
        """Deleted invoices should not count toward total invoiced."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("1000.00"))
        self._create_invoice(job, Decimal("1000.00"), status="DELETED")

        recalculate_job_invoicing_state(str(job.id), self.test_staff)

        job.refresh_from_db()
        self.assertFalse(job.fully_invoiced)
