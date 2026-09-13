"""The E2E cleanup removes a fake run's residue through the fake Xero (ADR 0060).

Business risk covered: the reset step and the teardown of a fake run call
the same removal routine a real run does; a fake that refused the delete or
the archive would leave every fake run failing its preflight on residue.
"""

import uuid
from collections.abc import Iterator

import pytest
from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.company.models import Company
from apps.diagnostics.services.e2e_xero_residue import XeroResidue, remove_residue_from_xero
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.fake.seed import seed_contacts
from apps.xero.fake.store import FakeXeroStore, Kind
from apps.xero.fake.testing import connected_to_the_fake

pytestmark = pytest.mark.django_db
TENANT = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def fake_xero() -> Iterator[FakeXeroStore]:
    with connected_to_the_fake(TENANT) as store:
        yield store


def test_the_cleanup_deletes_the_document_and_archives_the_contact(
    fake_xero: FakeXeroStore,
) -> None:
    company = Company.objects.create(
        name="[TEST] Residue Co",
        xero_contact_id=str(uuid.uuid4()),
        xero_last_modified=timezone.now(),
    )
    seed_contacts(fake_xero)
    api = AccountingApi(get_api_client())
    invoices = api.create_invoices(
        get_tenant_id(),
        invoices={
            "Invoices": [
                {
                    "Type": "ACCREC",
                    "Contact": {"ContactID": company.xero_contact_id},
                    "LineItems": [
                        {"Description": "x", "Quantity": 1, "UnitAmount": 10, "AccountCode": "200"}
                    ],
                    "Date": "2026-09-09",
                    "DueDate": "2026-09-16",
                    "Status": "DRAFT",
                }
            ]
        },
    ).invoices
    assert invoices is not None
    invoice_id = str(invoices[0].invoice_id)
    assert company.xero_contact_id is not None

    outcome = remove_residue_from_xero(
        XeroResidue(
            invoices={invoice_id: "INV-0001"}, contacts={company.xero_contact_id: company.name}
        ),
        "test",
    )

    assert not outcome.refused
    deleted = fake_xero.get(Kind.INVOICE, invoice_id)
    archived = fake_xero.get(Kind.CONTACT, company.xero_contact_id)
    assert deleted is not None and deleted.status == "DELETED"
    assert archived is not None and archived.status == "ARCHIVED"
