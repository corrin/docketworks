"""Purchase order line usage metadata tests."""

from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine


@pytest.fixture
def company_defaults(db: None) -> None:
    # Job.save -> generate_job_number -> CompanyDefaults.get_solo(); the
    # singleton cannot be lazily created (shop_company is NOT NULL).
    call_command("loaddata", "company_defaults")


@pytest.fixture
def auth_api(db, company_defaults):
    staff = Staff.objects.create(
        email="po-line-usage@example.test",
        first_name="Purchase",
        last_name="Usage",
    )
    client = APIClient()
    client.force_authenticate(user=staff)
    return client


def _material_usage(item_code: str) -> None:
    staff = Staff.objects.create(
        email=f"usage-{CostLine.objects.count()}@example.test",
        first_name="Usage",
        last_name="Staff",
    )
    job = Job.objects.create(
        name=f"Usage job {item_code}",
        job_number=Job.objects.count() + 1,
        staff=staff,
    )
    cost_set = CostSet.objects.get(job=job, kind="actual")
    CostLine.objects.create(
        cost_set=cost_set,
        kind="material",
        desc=f"Used {item_code}",
        quantity=Decimal("1.000"),
        unit_cost=Decimal("10.00"),
        unit_rev=Decimal("12.00"),
        accounting_date=timezone.localdate(),
        meta={"item_code": item_code},
    )


@pytest.mark.django_db
def test_purchase_order_detail_lines_include_material_times_used(auth_api):
    po = PurchaseOrder.objects.create(po_number="PO-USAGE-1")
    used_line = PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="Known item",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
        item_code="ABC-123",
    )
    unused_line = PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="New item",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
        item_code="XYZ-999",
    )
    blank_line = PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="Blank item",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
        item_code="",
    )

    _material_usage("ABC-123")
    _material_usage("ABC-123")
    _material_usage("OTHER")

    response = auth_api.get(f"/api/purchasing/purchase-orders/{po.id}/")

    assert response.status_code == 200
    lines = {line["id"]: line for line in response.json()["lines"]}
    assert lines[str(used_line.id)]["times_used"] == 2
    assert lines[str(unused_line.id)]["times_used"] == 0
    assert lines[str(blank_line.id)]["times_used"] == 0
