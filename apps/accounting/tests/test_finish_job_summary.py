"""Tests for the Finish Job customer balance.

The counter situations from KAN-323 are all the same arithmetic over different
invoice states, so they are one table. The cases that are not just arithmetic —
the price cap, excluded statuses, over-invoicing and GST rounding — get their own
tests.
"""

import uuid
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.accounting.models.invoice import Invoice
from apps.accounting.services.finish_job_summary import build_finish_job_summary
from apps.company.models import Company
from apps.job.models import Job
from apps.job.models.costing import CostSet
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

    def _job(self, pricing_methodology: str, revenue: Decimal) -> Job:
        job = Job(
            company=self.client_obj,
            name="Test Job",
            pricing_methodology=pricing_methodology,
        )
        job.save(staff=self.test_staff)
        basis = (
            job.latest_quote
            if pricing_methodology == "fixed_price"
            else job.latest_actual
        )
        self._add_revenue_line(basis, revenue)
        return job

    def _add_revenue_line(self, cost_set: CostSet, revenue: Decimal) -> None:
        from apps.job.models.costing import CostLine

        CostLine.objects.create(
            cost_set=cost_set,
            kind="adjust",
            desc="Test line",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=revenue,
            accounting_date=date.today(),
        )

    def _invoice(
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

    def test_counter_situations(self) -> None:
        """Every KAN-323 acceptance scenario, on a $1000 fixed-price job."""
        cases = [
            # label, invoices as (excl_tax, amount_due, status), expected total to pay
            ("nothing invoiced", [], Decimal("1150.00")),
            (
                "paid in advance",
                [(Decimal("1000"), Decimal("0.00"), "PAID")],
                Decimal("0.00"),
            ),
            (
                "unpaid advance invoice",
                [(Decimal("1000"), Decimal("1150.00"), "AUTHORISED")],
                Decimal("1150.00"),
            ),
            (
                "paid deposit, balance uninvoiced",
                [(Decimal("400"), Decimal("0.00"), "PAID")],
                Decimal("690.00"),
            ),
            (
                "unpaid progress invoice plus uninvoiced balance",
                [(Decimal("400"), Decimal("460.00"), "AUTHORISED")],
                Decimal("1150.00"),
            ),
            (
                "partly paid invoice",
                [(Decimal("1000"), Decimal("150.00"), "AUTHORISED")],
                Decimal("150.00"),
            ),
        ]

        for label, invoices, expected in cases:
            with self.subTest(label):
                job = self._job("fixed_price", Decimal("1000"))
                for amount, due, status in invoices:
                    self._invoice(job, amount, amount_due=due, status=status)

                summary = build_finish_job_summary(job)

                self.assertEqual(summary.total_to_pay_incl_gst, expected)

    def test_time_materials_value_is_limited_by_price_cap(self) -> None:
        job = self._job("time_materials", Decimal("5000"))
        job.price_cap = Decimal("3000.00")
        job.save(staff=self.test_staff)

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.job_value_excl_gst, Decimal("3000.00"))
        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("3000.00"))

    def test_voided_and_deleted_invoices_do_not_count(self) -> None:
        job = self._job("fixed_price", Decimal("1000"))
        self._invoice(job, Decimal("1000"), Decimal("1150.00"), "VOIDED")
        self._invoice(job, Decimal("1000"), Decimal("1150.00"), "DELETED")

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.valid_invoiced_excl_gst, Decimal("0.00"))
        self.assertEqual(summary.outstanding_invoiced_incl_gst, Decimal("0.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("1150.00"))

    def test_over_invoicing_is_reported_without_a_negative_remainder(self) -> None:
        """T&M actuals can land below what was already invoiced."""
        job = self._job("time_materials", Decimal("800"))
        self._invoice(job, Decimal("1000"), Decimal("0.00"), "PAID")

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.over_invoiced_excl_gst, Decimal("200.00"))
        self.assertEqual(summary.remaining_to_invoice_excl_gst, Decimal("0.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("0.00"))

    def test_gst_rounds_to_the_nearest_cent(self) -> None:
        """$333.33 x 15% = $49.9995, which must present as $50.00."""
        job = self._job("time_materials", Decimal("333.33"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.remaining_gst, Decimal("50.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("383.33"))

    def test_gst_uses_the_configured_rate(self) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.gst_rate = Decimal("0.1250")
        defaults.save()
        job = self._job("time_materials", Decimal("1000"))

        summary = build_finish_job_summary(job)

        self.assertEqual(summary.remaining_gst, Decimal("125.00"))
        self.assertEqual(summary.total_to_pay_incl_gst, Decimal("1125.00"))


class TestJobValueIsSharedWithReporting(BaseTestCase):
    """get_job_total_value must agree with the invoicing basis.

    It used to read CostSet.summary["rev"], a float mirror maintained by
    CostLine._update_cost_set_summary, while invoicing read total_revenue. Both
    now come from get_job_invoicing_basis, so a job cannot be reported at one
    value and invoiced at another.
    """

    def setUp(self) -> None:
        self.client_obj = Company.objects.create(
            name="Test Company",
            xero_last_modified=timezone.now(),
        )

    def _job_with_revenue(self, revenue: Decimal) -> Job:
        from apps.job.models.costing import CostLine

        job = Job(
            company=self.client_obj,
            name="Test Job",
            pricing_methodology="time_materials",
        )
        job.save(staff=self.test_staff)
        CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="adjust",
            desc="Test line",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=revenue,
            accounting_date=date.today(),
        )
        return job

    def test_reported_value_matches_the_invoicing_basis(self) -> None:
        from apps.accounting.services.invoice_calculation import (
            get_job_invoicing_basis,
        )
        from apps.job.services.job_service import get_job_total_value

        job = self._job_with_revenue(Decimal("1234.56"))

        self.assertEqual(
            get_job_total_value(job), get_job_invoicing_basis(job).target_total
        )

    def test_reported_value_respects_the_price_cap(self) -> None:
        """The old implementation ignored price_cap and over-reported."""
        from apps.job.services.job_service import get_job_total_value

        job = self._job_with_revenue(Decimal("5000"))
        job.price_cap = Decimal("3000.00")
        job.save(staff=self.test_staff)

        self.assertEqual(get_job_total_value(job), Decimal("3000.00"))
