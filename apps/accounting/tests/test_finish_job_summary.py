"""The Finish Job customer balance, ported from v1's suite.

The counter situations from KAN-323 are all the same arithmetic over
different invoice states, so they are one table. The cases that are not just
arithmetic — the price cap, excluded statuses, over-invoicing and GST
rounding — get their own tests.
"""

from decimal import Decimal

import pytest

from apps.accounting.services.finish_job_summary import build_finish_job_summary
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job, make_material_line
from apps.core.models import CompanyDefaults
from apps.job.models import Job

pytestmark = pytest.mark.django_db


@pytest.fixture
def company() -> Company:
    return make_company("Finish Job Ltd")


@pytest.fixture(autouse=True)
def _nz_gst() -> None:
    defaults = CompanyDefaults.get_solo()
    defaults.gst_rate = Decimal("0.1500")
    defaults.save(update_fields=["gst_rate"])


def _job(company: Company, staff: Staff, pricing_methodology: str, revenue: str) -> Job:
    job = make_job(company, staff, pricing_methodology=pricing_methodology)
    set_kind = "quote" if pricing_methodology == "fixed_price" else "actual"
    make_material_line(job, set_kind=set_kind, rev=revenue, cost="0.00")
    return job


class TestCounterSituations:
    """Every KAN-323 acceptance scenario, on a $1000 fixed-price job."""

    @pytest.mark.parametrize(
        ("label", "invoices", "expected_total_to_pay"),
        [
            ("nothing invoiced", [], Decimal("1150.00")),
            ("paid in advance", [("1000", "0.00", "PAID")], Decimal("0.00")),
            (
                "unpaid advance invoice",
                [("1000", "1150.00", "AUTHORISED")],
                Decimal("1150.00"),
            ),
            (
                "paid deposit, balance uninvoiced",
                [("400", "0.00", "PAID")],
                Decimal("690.00"),
            ),
            (
                "unpaid progress invoice plus uninvoiced balance",
                [("400", "460.00", "AUTHORISED")],
                Decimal("1150.00"),
            ),
            (
                "partly paid invoice",
                [("1000", "150.00", "AUTHORISED")],
                Decimal("150.00"),
            ),
        ],
    )
    def test_total_to_pay(
        self,
        company: Company,
        office_staff: Staff,
        label: str,
        invoices: list[tuple[str, str, str]],
        expected_total_to_pay: Decimal,
    ) -> None:
        job = _job(company, office_staff, "fixed_price", "1000.00")
        for amount, due, status in invoices:
            make_invoice(
                company,
                job=job,
                status=status,
                total_excl_tax=Decimal(amount),
                amount_due=Decimal(due),
            )

        summary = build_finish_job_summary(job)

        assert summary.total_to_pay_incl_gst == expected_total_to_pay, label


class TestEdgeCases:
    def test_time_materials_value_is_limited_by_price_cap(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _job(company, office_staff, "time_materials", "5000.00")
        job.price_cap = Decimal("3000.00")
        job.save(staff=office_staff, update_fields=["price_cap"])

        summary = build_finish_job_summary(job)

        assert summary.job_value_excl_gst == Decimal("3000.00")
        assert summary.remaining_to_invoice_excl_gst == Decimal("3000.00")

    def test_voided_and_deleted_invoices_do_not_count(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _job(company, office_staff, "fixed_price", "1000.00")
        for status in ("VOIDED", "DELETED"):
            make_invoice(
                company,
                job=job,
                status=status,
                total_excl_tax=Decimal("1000"),
                amount_due=Decimal("1150.00"),
            )

        summary = build_finish_job_summary(job)

        assert summary.valid_invoiced_excl_gst == Decimal("0.00")
        assert summary.outstanding_invoiced_incl_gst == Decimal("0.00")
        assert summary.total_to_pay_incl_gst == Decimal("1150.00")

    def test_over_invoicing_is_reported_without_a_negative_remainder(
        self, company: Company, office_staff: Staff
    ) -> None:
        """T&M actuals can land below what was already invoiced."""
        job = _job(company, office_staff, "time_materials", "800.00")
        make_invoice(
            company,
            job=job,
            status="PAID",
            total_excl_tax=Decimal("1000"),
            amount_due=Decimal("0.00"),
        )

        summary = build_finish_job_summary(job)

        assert summary.over_invoiced_excl_gst == Decimal("200.00")
        assert summary.remaining_to_invoice_excl_gst == Decimal("0.00")
        assert summary.total_to_pay_incl_gst == Decimal("0.00")

    def test_gst_rounds_to_the_nearest_cent(self, company: Company, office_staff: Staff) -> None:
        """$333.33 x 15% = $49.9995, which must present as $50.00."""
        job = _job(company, office_staff, "time_materials", "333.33")

        summary = build_finish_job_summary(job)

        assert summary.remaining_gst == Decimal("50.00")
        assert summary.total_to_pay_incl_gst == Decimal("383.33")

    def test_gst_uses_the_configured_rate(self, company: Company, office_staff: Staff) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.gst_rate = Decimal("0.1250")
        defaults.save(update_fields=["gst_rate"])
        job = _job(company, office_staff, "time_materials", "1000.00")

        summary = build_finish_job_summary(job)

        assert summary.remaining_gst == Decimal("125.00")
        assert summary.total_to_pay_incl_gst == Decimal("1125.00")
