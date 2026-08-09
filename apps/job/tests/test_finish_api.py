"""The Finish Job endpoints: balance payload, checklist updates, invoice list.

Business risk covered: this is the wire contract the Finish tab drives the
invoice E2E spec through — a wrong balance shows a customer the wrong amount
to pay, and a checklist write that skips Job.save() loses its audit event.
"""

import json
from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job, make_material_line
from apps.core.models import CompanyDefaults
from apps.job.models import Job, JobEvent

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _nz_gst() -> None:
    defaults = CompanyDefaults.get_solo()
    defaults.gst_rate = Decimal("0.1500")
    defaults.save(update_fields=["gst_rate"])


@pytest.fixture
def company() -> Company:
    return make_company("Finish API Ltd")


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    new_job = make_job(company, office_staff, pricing_methodology="fixed_price")
    make_material_line(new_job, set_kind="quote", rev="1000.00", cost="0.00")
    return new_job


class TestFinishRetrieve:
    def test_returns_balance_and_checklist(self, api: Client, job: Job) -> None:
        response = api.get(f"/api/job/jobs/{job.id}/finish/")

        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["job_value_excl_gst"] == "1000.00"
        assert body["summary"]["total_to_pay_incl_gst"] == "1150.00"
        assert body["checklist"] == {
            "foreman_signed_off": False,
            "timesheets_collected": False,
            "materials_checked": False,
            "customer_called": False,
            "released": False,
        }

    def test_unknown_job_is_404(self, api: Client) -> None:
        response = api.get("/api/job/jobs/00000000-0000-0000-0000-0000000000aa/finish/")
        assert response.status_code == 404

    def test_balance_reflects_invoices(self, api: Client, job: Job, company: Company) -> None:
        make_invoice(
            company,
            job=job,
            status="PAID",
            total_excl_tax=Decimal("1000"),
            amount_due=Decimal("0.00"),
        )

        body = api.get(f"/api/job/jobs/{job.id}/finish/").json()

        assert body["summary"]["remaining_to_invoice_excl_gst"] == "0.00"
        assert body["summary"]["total_to_pay_incl_gst"] == "0.00"


class TestChecklistUpdate:
    def test_tick_persists_and_audits(self, api: Client, job: Job) -> None:
        response = api.patch(
            f"/api/job/jobs/{job.id}/finish/",
            data=json.dumps({"foreman_signed_off": True}),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["checklist"]["foreman_signed_off"] is True
        job.refresh_from_db()
        assert job.foreman_signed_off
        # The tick reaches the audit trail through Job.save's field tracking.
        assert JobEvent.objects.filter(job=job).exists()

    def test_unknown_item_is_rejected(self, api: Client, job: Job) -> None:
        response = api.patch(
            f"/api/job/jobs/{job.id}/finish/",
            data=json.dumps({"paid_in_cash": True}),
            content_type="application/json",
        )
        assert response.status_code == 422
        job.refresh_from_db()
        assert not job.foreman_signed_off


class TestInvoicesRetrieve:
    def test_lists_job_invoices(self, api: Client, job: Job, company: Company) -> None:
        invoice = make_invoice(company, job=job, total_excl_tax=Decimal("400"))
        make_invoice(company)  # an invoice not linked to the job must not appear

        response = api.get(f"/api/job/jobs/{job.id}/invoices/")

        assert response.status_code == 200
        invoices = response.json()["invoices"]
        assert len(invoices) == 1
        assert invoices[0]["number"] == invoice.number
        assert invoices[0]["total_excl_tax"] == 400.00

    def test_conditional_get(self, api: Client, job: Job) -> None:
        first = api.get(f"/api/job/jobs/{job.id}/invoices/")
        etag = first.headers["ETag"]

        second = api.get(f"/api/job/jobs/{job.id}/invoices/", HTTP_IF_NONE_MATCH=etag)

        assert second.status_code == 304
