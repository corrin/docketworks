"""Proof that the cost-line approve seam is closed.

``POST /api/job/cost_lines/{id}/approve/`` was deferred out of the Phase 3b-2
costing slice because ``purchasing.consume_stock`` did not exist. These tests
exercise the real endpoint against real stock: approving a material line draws
the stock row down and reprices the line from it, which is the behaviour the
seam was standing in for.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate
from apps.company.tests.job_fixtures import make_job, ordinary_time_pay_item
from apps.core.models import CompanyDefaults
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.purchasing.tests.conftest import make_stock

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.purchasing.tests.urls"),
]


def _approve_url(cost_line: CostLine) -> str:
    return f"/api/job/cost_lines/{cost_line.id}/approve/"


def _material_line(job: Job, *, stock_id: str | None, quantity: str = "3.000") -> CostLine:
    line = CostLine(
        cost_set=job.latest_actual,
        kind="material",
        desc="Workshop-entered material",
        quantity=Decimal(quantity),
        unit_cost=Decimal("1.00"),
        # Shop jobs never carry revenue (CostLine.save enforces it).
        unit_rev=Decimal("0.00") if job.shop_job else Decimal("1.00"),
        accounting_date=timezone.localdate(),
        ext_refs={"stock_id": stock_id} if stock_id else {},
        approved=False,
    )
    line.save()
    return line


@pytest.mark.usefixtures("company_defaults")
class TestApproveMaterialLineConsumesStock:
    def test_approving_draws_the_stock_down_and_reprices_the_line(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        stock = make_stock(
            stock_holding_job, description="4mm plate", quantity="10.00", unit_cost="30.00"
        )
        line = _material_line(job, stock_id=str(stock.id), quantity="3.000")

        response = client.post(_approve_url(line))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert Decimal(body["remaining_quantity"]) == Decimal("7.00")

        stock.refresh_from_db()
        assert stock.quantity == Decimal("7.00")

        line.refresh_from_db()
        assert line.approved is True
        # Repriced from the stock row, not from whatever the workshop typed.
        assert line.desc == "4mm plate"
        assert line.unit_cost == Decimal("30.00")
        assert line.unit_rev == Decimal("36.00")
        assert line.ext_refs["stock_id"] == str(stock.id)

    def test_approval_is_recorded_against_the_approving_staff_member(
        self, client: Client, stock_holding_job: Job, job: Job, office_staff: Staff
    ) -> None:
        stock = make_stock(stock_holding_job)
        line = _material_line(job, stock_id=str(stock.id), quantity="1.000")

        client.post(_approve_url(line))

        line.refresh_from_db()
        assert line.meta["consumed_by"] == str(office_staff.id)

    def test_a_material_line_without_a_stock_reference_is_400(
        self, client: Client, job: Job
    ) -> None:
        line = _material_line(job, stock_id=None)

        response = client.post(_approve_url(line))

        assert response.status_code == 400
        assert "missing item code" in response.json()["detail"]
        line.refresh_from_db()
        assert line.approved is False

    def test_a_dangling_stock_reference_is_404(self, client: Client, job: Job) -> None:
        line = _material_line(job, stock_id=str(uuid4()))

        assert client.post(_approve_url(line)).status_code == 404

    def test_approving_twice_is_rejected_and_consumes_stock_once(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        stock = make_stock(stock_holding_job, quantity="10.00")
        line = _material_line(job, stock_id=str(stock.id), quantity="3.000")

        first = client.post(_approve_url(line))
        second = client.post(_approve_url(line))

        assert first.status_code == 200
        assert second.status_code == 400
        assert "already approved" in second.json()["detail"]
        stock.refresh_from_db()
        assert stock.quantity == Decimal("7.00")

    def test_a_shop_job_is_never_billed_for_consumed_stock(
        self, client: Client, stock_holding_job: Job, office_staff: Staff
    ) -> None:
        shop_job = make_job(CompanyDefaults.get_solo().shop_company, office_staff, name="Shop work")
        assert shop_job.shop_job
        stock = make_stock(stock_holding_job, quantity="10.00", unit_cost="30.00")
        line = _material_line(shop_job, stock_id=str(stock.id), quantity="1.000")

        client.post(_approve_url(line))

        line.refresh_from_db()
        assert line.unit_rev == Decimal("0.00")


@pytest.mark.usefixtures("company_defaults")
class TestApproveNonMaterialLine:
    def test_a_time_line_is_approved_without_touching_stock(
        self, client: Client, job: Job, office_staff: Staff
    ) -> None:
        line = CostLine(
            cost_set=job.latest_actual,
            kind="time",
            desc="Workshop time",
            quantity=Decimal("2.000"),
            unit_cost=Decimal("48.00"),
            unit_rev=Decimal("120.00"),
            accounting_date=timezone.localdate(),
            staff=office_staff,
            labour_subtype=LabourSubtype.default_workshop(),
            approved=False,
        )
        line.xero_pay_item_id = ordinary_time_pay_item().pk
        line.save()

        response = client.post(_approve_url(line))

        assert response.status_code == 200
        assert response.json()["remaining_quantity"] is None
        line.refresh_from_db()
        assert line.approved is True


@pytest.mark.usefixtures("company_defaults")
class TestApproveAuthorisation:
    def test_workshop_staff_may_not_approve(
        self, workshop_staff: Staff, stock_holding_job: Job, job: Job
    ) -> None:
        stock = make_stock(stock_holding_job)
        line = _material_line(job, stock_id=str(stock.id), quantity="1.000")
        workshop_client = Client()
        authenticate(workshop_client, workshop_staff)

        response = workshop_client.post(_approve_url(line))

        assert response.status_code == 403
        line.refresh_from_db()
        assert line.approved is False
