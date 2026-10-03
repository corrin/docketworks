"""The seed turns the mirror into the fake's Xero, and refuses what is not Xero's (ADR 0060)."""

import uuid
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Invoice
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_quote
from apps.core.models import CompanyDefaults
from apps.purchasing.models import PurchaseOrder
from apps.xero.fake.models import (
    FakeAccount,
    FakeContact,
    FakeInvoice,
    FakeOrganisation,
    FakePurchaseOrder,
    FakeQuote,
)
from apps.xero.fake.seed import SeedError, recorded_body, seed_accounting
from apps.xero.fake.tests.conftest import TENANT, sdk_client_answering
from apps.xero.models import XeroAccount
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
    tenant: str,
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
    empty = Company.objects.create(
        name="[TEST] Empty Body Co",
        xero_contact_id=str(uuid.uuid4()),
        xero_last_modified=timezone.now(),
        raw_json={},
    )
    invoice = _mirrored_invoice(pushed)

    counts = seed_accounting(tenant)

    assert counts["contacts"] == 3
    from_columns = FakeContact.held(tenant, str(empty.xero_contact_id))
    assert from_columns is not None and from_columns.name == "[TEST] Empty Body Co"
    assert counts["invoices"] == 1
    mirrored = FakeContact.held(tenant, mirrored_id)
    assert mirrored is not None and mirrored.status == "ACTIVE"
    assert mirrored.name == "[TEST] Mirrored Co"
    held = FakeContact.held(tenant, str(pushed.xero_contact_id))
    assert held is not None and held.name == "[TEST] Pushed Co"
    seeded_invoice = FakeInvoice.held(tenant, str(invoice.xero_id))
    assert seeded_invoice is not None
    assert seeded_invoice.number == "INV-0016"
    assert seeded_invoice.status == "PAID"
    assert str(seeded_invoice.to_wire()["Date"]).startswith("/Date(")
    # The SDK reads the seeded body back exactly as it read the recording.
    again = (
        AccountingApi(sdk_client_answering({"Invoices": [seeded_invoice.to_wire()]}))
        .get_invoice(TENANT, "any")
        .invoices[0]
    )
    assert Decimal(str(again.total)) == Decimal("541.25")


def test_the_seed_renders_a_mirrored_purchase_order_with_its_lines_and_supplier(
    tenant: str,
) -> None:
    # What a restored order looks like once the re-seed has linked it and the
    # sync has stored Xero's copy: the fake has to hold it, or a push for that
    # order updates something the fake has never seen.
    recorded = recorded_body("purchase_order")
    answer = AccountingApi(sdk_client_answering(recorded)).get_purchase_order(TENANT, "any")
    assert answer.purchase_orders
    fetched = answer.purchase_orders[0]
    assert fetched.contact is not None and fetched.line_items is not None
    supplier = Company.objects.create(
        name="[TEST] Supplier Co",
        xero_contact_id=str(fetched.contact.contact_id),
        xero_last_modified=timezone.now(),
    )
    order = PurchaseOrder.objects.create(
        xero_id=uuid.UUID(str(fetched.purchase_order_id)),
        xero_tenant_id=TENANT,
        supplier=supplier,
        created_by=Staff.get_automation_user(),
        po_number=str(fetched.purchase_order_number),
        status="submitted",
        raw_json=process_xero_data(fetched),
    )
    PurchaseOrder.objects.create(
        supplier=supplier, created_by=Staff.get_automation_user(), status="draft"
    )

    counts = seed_accounting(tenant)

    # The draft is not in Xero, so it is not in the fake either.
    assert counts["purchase_orders"] == 1
    assert FakePurchaseOrder.objects.filter(tenant_id=tenant).count() == 1
    held = FakePurchaseOrder.held(tenant, str(order.xero_id))
    assert held is not None
    assert held.number == order.po_number
    assert held.lines.count() == len(fetched.line_items)
    assert held.contact == FakeContact.held(tenant, str(supplier.xero_contact_id))


def test_the_seed_renders_deleted_quotes_that_share_a_number(tenant: str) -> None:
    # Xero reissues a deleted quote's number, so a real organisation holds
    # several deleted quotes under one (the Demo Company: three QU-0013). A
    # fake that held numbers unique across deleted quotes refused the mirror
    # of a real organisation, and no E2E run could start.
    recorded = recorded_body("quote_delete")
    answer = AccountingApi(sdk_client_answering(recorded)).get_quotes(TENANT)
    assert answer.quotes
    deleted = answer.quotes[0]
    assert deleted.contact is not None
    company = Company.objects.create(
        name="[TEST] Quoted Co",
        xero_contact_id=str(deleted.contact.contact_id),
        xero_last_modified=timezone.now(),
    )
    for _ in range(2):
        quote = make_quote(company, number=str(deleted.quote_number))
        # Two quotes, so two lines: only the number is shared.
        for line in deleted.line_items or []:
            line.line_item_id = str(uuid.uuid4())
        quote.raw_json = process_xero_data(deleted)
        quote.save(update_fields=["raw_json"])

    counts = seed_accounting(tenant)

    assert counts["quotes"] == 2
    assert FakeQuote.objects.filter(tenant_id=tenant, status="DELETED").count() == 2


def test_a_readonly_stub_row_is_refused_not_rendered(tenant: str) -> None:
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
        seed_accounting(tenant)


def test_the_command_refuses_a_full_store_without_replace(tenant: str) -> None:
    del tenant
    CompanyDefaults.objects.filter(pk=CompanyDefaults.singleton_instance_id).update(
        xero_tenant_id=TENANT, company_name="Seed Co"
    )
    CompanyDefaults.clear_cache()
    with pytest.raises(CommandError, match="already holds"):
        call_command("fake_xero_seed")
    call_command("fake_xero_seed", "--replace")
    assert FakeOrganisation.objects.get(tenant_id=TENANT).name == "Seed Co (FAKE XERO)"


def test_the_seed_holds_only_the_tenant_s_own_accounts(tenant: str) -> None:
    """A code the tenant uses may also sit on a row from another tenant, or on one never stamped."""
    fetched = (
        AccountingApi(sdk_client_answering(recorded_body("accounts")))
        .get_accounts(TENANT)
        .accounts[0]
    )
    body = process_xero_data(fetched)

    def account(name: str, tenant: str | None) -> XeroAccount:
        return XeroAccount.objects.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id=tenant,
            account_code=str(fetched.code),
            account_name=name,
            xero_last_modified=timezone.now(),
            raw_json=body,
        )

    own = account("[TEST] Own tenant", TENANT)
    account("[TEST] Another tenant", str(uuid.uuid4()))
    account("[TEST] Never stamped", None)

    counts = seed_accounting(tenant)

    assert counts["accounts"] == 1
    assert FakeAccount.held(tenant, str(own.xero_id)) is not None
