"""The seed turns the mirror into the fake's Xero, and refuses what is not Xero's (ADR 0060)."""

import uuid
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Invoice
from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.xero.fake.models import FakeXeroObject
from apps.xero.fake.seed import SeedError, recorded_body, seed_accounting
from apps.xero.fake.store import FakeXeroStore, Kind
from apps.xero.fake.tests.conftest import TENANT, sdk_client_answering
from apps.xero.tests.xero_fixtures import make_contact_raw_json
from apps.xero.transforms import process_xero_data

pytestmark = pytest.mark.django_db


def _mirrored_invoice(company: Company) -> Invoice:
    """An Invoice row as the sync would have stored it: raw_json from a real recording."""
    recorded = recorded_body("invoice")
    fetched = AccountingApi(sdk_client_answering(recorded)).get_invoice(TENANT, "any").invoices[0]
    return Invoice.objects.create(
        xero_id=uuid.UUID(str(fetched.invoice_id)),
        xero_tenant_id=TENANT,
        company=company,
        number=str(fetched.invoice_number),
        date=fetched.date,
        due_date=fetched.due_date,
        status="paid",
        total_excl_tax=Decimal("470.65"),
        tax=Decimal("70.60"),
        total_incl_tax=Decimal("541.25"),
        amount_due=Decimal("0"),
        xero_last_modified=timezone.now(),
        raw_json=process_xero_data(fetched),
    )


def test_the_seed_renders_mirrored_and_pushed_companies_and_mirrored_documents(
    store: FakeXeroStore,
) -> None:
    mirrored_id = str(uuid.uuid4())
    Company.objects.create(
        name="[TEST] Mirrored Co",
        xero_contact_id=mirrored_id,
        xero_last_modified=timezone.now(),
        raw_json=make_contact_raw_json(mirrored_id, "[TEST] Mirrored Co"),
    )
    pushed = Company.objects.create(
        name="[TEST] Pushed Co",
        xero_contact_id=str(uuid.uuid4()),
        xero_last_modified=timezone.now(),
    )
    Company.objects.create(name="[TEST] Local Only", xero_last_modified=timezone.now())
    invoice = _mirrored_invoice(pushed)

    counts = seed_accounting(store)

    assert counts["contacts"] == 2
    assert counts["invoices"] == 1
    mirrored = store.get(Kind.CONTACT, mirrored_id)
    assert mirrored is not None and mirrored.body["ContactStatus"] == "ACTIVE"
    assert mirrored.name == "[TEST] Mirrored Co"
    held = store.get(Kind.CONTACT, str(pushed.xero_contact_id))
    assert held is not None and held.body["Name"] == "[TEST] Pushed Co"
    seeded_invoice = store.get(Kind.INVOICE, str(invoice.xero_id))
    assert seeded_invoice is not None
    assert seeded_invoice.number == "INV-0016"
    assert seeded_invoice.status == "PAID"
    assert str(seeded_invoice.body["Date"]).startswith("/Date(")
    # The SDK reads the seeded body back exactly as it read the recording.
    again = (
        AccountingApi(sdk_client_answering({"Invoices": [seeded_invoice.body]}))
        .get_invoice(TENANT, "any")
        .invoices[0]
    )
    assert Decimal(str(again.total)) == Decimal("541.25")


def test_a_readonly_stub_row_is_refused_not_rendered(store: FakeXeroStore) -> None:
    company = Company.objects.create(
        name="[TEST] Stub Co", xero_contact_id=str(uuid.uuid4()), xero_last_modified=timezone.now()
    )
    Invoice.objects.create(
        xero_id=uuid.uuid4(),
        xero_tenant_id=TENANT,
        company=company,
        number="INV-E2E-DEADBEEF",
        date=timezone.localdate(),
        due_date=timezone.localdate(),
        status="submitted",
        total_excl_tax=Decimal("1"),
        tax=Decimal("0"),
        total_incl_tax=Decimal("1"),
        amount_due=Decimal("1"),
        xero_last_modified=timezone.now(),
        raw_json={"_e2e_stub": True},
    )
    with pytest.raises(SeedError, match="readonly provider"):
        seed_accounting(store)


def test_the_command_refuses_a_full_store_without_replace(store: FakeXeroStore) -> None:
    del store
    CompanyDefaults.objects.filter(pk=CompanyDefaults.singleton_instance_id).update(
        xero_tenant_id=TENANT, company_name="Seed Co"
    )
    CompanyDefaults.clear_cache()
    with pytest.raises(CommandError, match="already holds"):
        call_command("fake_xero_seed")
    call_command("fake_xero_seed", "--replace")
    assert FakeXeroObject.objects.filter(tenant_id=TENANT, kind=Kind.ORGANISATION).count() == 1
    organisation = FakeXeroObject.objects.get(tenant_id=TENANT, kind=Kind.ORGANISATION)
    assert organisation.name == "Seed Co (FAKE XERO)"
