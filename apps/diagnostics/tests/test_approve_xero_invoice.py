"""approve_xero_invoice makes the approval a person makes in Xero (KAN-381's E2E).

Business risk covered: the void-offer spec stands on an invoice that is
approved in Xero AND in Docketworks' copy. A command that approved only one
side would have the spec test the disagreement path instead of the offer.
"""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Invoice
from apps.company.models import Company
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.fake.models import FakeInvoice
from apps.xero.fake.seed import seed_contacts
from apps.xero.fake.testing import connected_to_the_fake

pytestmark = pytest.mark.django_db
TENANT = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def fake_xero() -> Iterator[str]:
    with connected_to_the_fake(TENANT) as tenant:
        yield tenant


def test_the_draft_is_approved_in_xero_and_in_docketworks(fake_xero: str) -> None:
    company = Company.objects.create(
        name="[TEST] Approve Co",
        xero_contact_id=str(uuid.uuid4()),
        xero_tenant_id="test-tenant",
        xero_last_modified=timezone.now(),
    )
    seed_contacts(fake_xero)
    created = (
        AccountingApi(get_api_client())
        .create_invoices(
            get_tenant_id(),
            invoices={
                "Invoices": [
                    {
                        "Type": "ACCREC",
                        "Contact": {"ContactID": company.xero_contact_id},
                        "LineItems": [
                            {
                                "Description": "x",
                                "Quantity": 1,
                                "UnitAmount": 10,
                                "AccountCode": "200",
                            }
                        ],
                        "Date": "2026-09-09",
                        "DueDate": "2026-09-16",
                        "Status": "DRAFT",
                    }
                ]
            },
        )
        .invoices
    )
    assert created is not None
    xero_id = str(created[0].invoice_id)
    Invoice.objects.create(
        xero_id=xero_id,
        xero_tenant_id=get_tenant_id(),
        number=str(created[0].invoice_number),
        company=company,
        date="2026-09-09",
        status="SUBMITTED",
        total_excl_tax=Decimal("10"),
        tax=Decimal("1.5"),
        total_incl_tax=Decimal("11.5"),
        amount_due=Decimal("11.5"),
        xero_last_modified=timezone.now(),
        raw_json={},
    )

    call_command("approve_xero_invoice", xero_id)

    held = FakeInvoice.held(fake_xero, xero_id)
    assert held is not None and held.status == "AUTHORISED"
    assert Invoice.objects.get(xero_id=xero_id).status == "AUTHORISED"
