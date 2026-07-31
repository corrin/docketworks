"""Tests for the Finish Job customer balance summary.

Each test names a counter situation from KAN-323: what the customer must pay,
including GST, given what has already been invoiced and paid.
"""

import uuid
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.models.invoice import Invoice
from apps.accounting.services.finish_job_summary import (
    build_finish_job_summary,
    get_job_for_finish_summary,
)
from apps.company.models import Company
from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults


class TestFinishJobSummary(BaseTestCase):
    def setUp(self) -> None:
        self.client_obj = Company.objects.create(
            name="Test Company",
            xero_last_modified=timezone.now(),
        )
        defaults = CompanyDefaults.get_solo()
        defaults.gst_rate = Decimal("0.1500")
        defaults.save()

    def _create_job(self, pricing_methodology: str = "time_materials") -> Job:
        job = Job(
            company=self.client_obj,
            name="Test Job",
            pricing_methodology=pricing_methodology,
        )
        job.save(staff=self.test_staff)
        return job

    def _add_revenue_line(self, cost_set: CostSet, revenue: Decimal) -> None:
        CostLine.objects.create(
            cost_set=cost_set,
            kind="adjust",
            desc="Test line",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=revenue,
            accounting_date=date.today(),
        )

    def _create_invoice(
        self,
        job: Job,
        amount: Decimal,
        amount_due: Decimal = Decimal("0.00"),
        status: str = "AUTHORISED",
    ) -> Invoice:
        return Invoice.objects.create(
            job=job,
            company=self.client_obj,
            xero_id=uuid.uuid4(),
            number=f"INV-{uuid.uuid4().hex[:8]}",
            status=status,
            total_excl_tax=amount,
            tax=(amount * Decimal("0.15")).quantize(Decimal("0.01")),
            total_incl_tax=amount * Decimal("1.15"),
            amount_due=amount_due,
            date=date.today(),
            xero_last_modified=timezone.now(),
            raw_json={},
        )

    # --- Job value basis ---

    def test_fixed_price_value_is_the_quote(self) -> None:
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("5000"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.basis, "quote")
        self.assertEqual(summary.job_value_excl_gst, Decimal("5000.00"))

    def test_time_materials_value_is_actual_revenue(self) -> None:
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("1234.56"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.basis, "actual_revenue")
        self.assertEqual(summary.job_value_excl_gst, Decimal("1234.56"))

    def test_time_materials_value_is_limited_by_price_cap(self) -> None:
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("5000"))
        job.price_cap = Decimal("3000.00")
        job.save(staff=self.test_staff)

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.job_value_excl_gst, Decimal("3000.00"))
        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("3000.00"))

    def test_fixed_price_without_a_quote_is_worth_nothing_yet(self) -> None:
        """A job created but not yet quoted must still render a balance."""
        job = self._create_job("fixed_price")

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.job_value_excl_gst, Decimal("0.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("0.00"))

    # --- Counter situations ---

    def test_nothing_invoiced_charges_the_whole_job_plus_gst(self) -> None:
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("1000"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.valid_invoiced_excl_gst, Decimal("0.00"))
        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("1000.00"))
        self.assertEqual(summary.remaining_gst, Decimal("150.00"))
        self.assertEqual(summary.remaining_to_invoice_incl_gst, Decimal("1150.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("1150.00"))

    def test_paid_advance_invoice_leaves_nothing_to_pay(self) -> None:
        """Invoiced in full before work started, and the customer has paid."""
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("1000"))
        self._create_invoice(
            job, Decimal("1000"), amount_due=Decimal("0.00"), status="PAID"
        )

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("0.00"))
        self.assertEqual(summary.remaining_gst, Decimal("0.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("0.00"))
        self.assertEqual(summary.over_invoiced_excl_gst, Decimal("0.00"))

    def test_unpaid_advance_invoice_is_the_amount_to_pay(self) -> None:
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("1000"))
        self._create_invoice(job, Decimal("1000"), amount_due=Decimal("1150.00"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("0.00"))
        self.assertEqual(summary.outstanding_invoiced_incl_gst, Decimal("1150.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("1150.00"))

    def test_paid_deposit_leaves_only_the_uninvoiced_balance(self) -> None:
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("1000"))
        self._create_invoice(
            job, Decimal("400"), amount_due=Decimal("0.00"), status="PAID"
        )

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.outstanding_invoiced_incl_gst, Decimal("0.00"))
        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("600.00"))
        self.assertEqual(summary.remaining_gst, Decimal("90.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("690.00"))

    def test_unpaid_progress_invoice_and_balance_are_both_owed(self) -> None:
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("1000"))
        self._create_invoice(job, Decimal("400"), amount_due=Decimal("460.00"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.outstanding_invoiced_incl_gst, Decimal("460.00"))
        self.assertEqual(summary.remaining_to_invoice_incl_gst, Decimal("690.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("1150.00"))

    def test_partly_paid_invoice_owes_only_its_outstanding_balance(self) -> None:
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("1000"))
        self._create_invoice(job, Decimal("1000"), amount_due=Decimal("150.00"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("150.00"))

    # --- Excluded invoices ---

    def test_voided_and_deleted_invoices_do_not_count(self) -> None:
        job = self._create_job("fixed_price")
        self._add_revenue_line(job.latest_quote, Decimal("1000"))
        self._create_invoice(
            job, Decimal("1000"), amount_due=Decimal("1150.00"), status="VOIDED"
        )
        self._create_invoice(
            job, Decimal("1000"), amount_due=Decimal("1150.00"), status="DELETED"
        )

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.valid_invoiced_excl_gst, Decimal("0.00"))
        self.assertEqual(summary.outstanding_invoiced_incl_gst, Decimal("0.00"))
        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("1000.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("1150.00"))

    # --- Over-invoicing ---

    def test_over_invoicing_is_reported_without_a_negative_remainder(self) -> None:
        """T&M actuals can fall below what was already invoiced."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("800"))
        self._create_invoice(
            job, Decimal("1000"), amount_due=Decimal("0.00"), status="PAID"
        )

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.over_invoiced_excl_gst, Decimal("200.00"))
        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("0.00"))
        self.assertEqual(summary.remaining_gst, Decimal("0.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("0.00"))

    def test_over_invoiced_and_unpaid_still_owes_the_invoice(self) -> None:
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("800"))
        self._create_invoice(job, Decimal("1000"), amount_due=Decimal("1150.00"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.over_invoiced_excl_gst, Decimal("200.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("1150.00"))

    # --- GST arithmetic ---

    def test_gst_rounds_to_the_nearest_cent(self) -> None:
        """$333.33 x 15% = $49.9995, which must present as $50.00."""
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("333.33"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.remaining_gst, Decimal("50.00"))
        self.assertEqual(summary.remaining_to_invoice_incl_gst, Decimal("383.33"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("383.33"))

    def test_summary_query_count_does_not_grow_with_cost_lines(self) -> None:
        """The job value sums cost lines, so the basis cost set must be prefetched."""
        job = self._create_job("time_materials")
        for _ in range(10):
            self._add_revenue_line(job.latest_actual, Decimal("10"))

        with CaptureQueriesContext(connection) as few_lines:
            build_finish_job_summary(get_job_for_finish_summary(job.id))

        for _ in range(20):
            self._add_revenue_line(job.latest_actual, Decimal("10"))

        with CaptureQueriesContext(connection) as many_lines:
            build_finish_job_summary(get_job_for_finish_summary(job.id))

        self.assertEqual(len(many_lines), len(few_lines))

    def test_gst_uses_the_configured_rate(self) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.gst_rate = Decimal("0.1250")
        defaults.save()
        job = self._create_job("time_materials")
        self._add_revenue_line(job.latest_actual, Decimal("1000"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.remaining_gst, Decimal("125.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("1125.00"))
