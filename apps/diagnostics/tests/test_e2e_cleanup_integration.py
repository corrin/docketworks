"""E2E residue removal against the demo organisation (ADR 0050).

Two scenarios, one per question the two commands answer.

``e2e_cleanup`` undoes a run: a real contact with a real invoice against it is
built through the app's own provider, and the cleanup must leave the invoice
DELETED and the contact ARCHIVED. The archive assertion is the load-bearing
one. Xero refuses to archive a contact that still has transactions against it,
so it can only pass if the invoice was removed first — which is the ordering
this file exists to hold. A fake provider cannot prove that: it returns
whatever the author assumed about the vendor's refusal, which is exactly the
belief that let the residue accumulate.

``e2e_xero_sweep`` clears what the database has forgotten: a contact created
directly in Xero, with no local row at all, must end the sweep archived.

Both read the result back from Xero rather than trusting a return value. The
sweep acts on every E2E-named object in the organisation, not only the probe —
that is what it is for — so this file refuses to run while an E2E suite holds
the lock, since it would otherwise take away the contacts a spec is using.

Re-runnable by construction: the probes are new each run, so anything an
aborted run strands is inert rather than in the way. Not cheap, though — it
pages the organisation's invoices, quotes, purchase orders and contacts, so run
it when the change warrants it rather than on a loop.
"""

import secrets
import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper
from xero_python.accounting import AccountingApi, Contact

from apps.accounting.models import Invoice
from apps.accounting.registry import get_provider
from apps.accounting.types import DocumentLineItem, InvoicePayload
from apps.company.models import Company
from apps.company.services.company_rest_service import CompanyRestService
from apps.core.test_data import TEST_DATA_PREFIX
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.e2e_artifacts import E2E_LOCK_FILE
from apps.xero.models import XeroAccount
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.sync import one_way_sync_all_xero_data

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

SALES_ACCOUNT_NAME = "Sales"


@pytest.fixture(autouse=True)
def _guards(integration_credentials: None) -> None:  # noqa: ARG001 -- the fixture's side effect is the point
    assert_not_production_target()
    assert_xero_writes_enabled("the E2E residue integration tests")
    if E2E_LOCK_FILE.exists():
        raise RuntimeError(
            f"An E2E run holds {E2E_LOCK_FILE}; removing residue now would take its objects away."
        )


@pytest.fixture(autouse=True)
def _no_sequence_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the cleanup's explicit COMMIT from escaping pytest's savepoint.

    ``sync_sequences`` is local bookkeeping about this throwaway database, not
    part of the vendor behaviour under test, and its COMMIT would end the
    rollback that keeps the test's own rows out of dev.
    """
    real_call_command = call_command

    def skip_sequence_sync(command: str, *args: str, **kwargs: object) -> None:
        if command != "sync_sequences":
            real_call_command(command, *args, **kwargs)

    monkeypatch.setattr(
        "apps.diagnostics.management.commands.e2e_cleanup.call_command", skip_sequence_sync
    )


@pytest.fixture
def syncing_enabled(settings: SettingsWrapper) -> None:
    """Let the inbound sync run against the demo tenant.

    ``sync.py`` reads DEBUG-off as production and aborts any sync of a
    non-production tenant; pytest forces DEBUG off. This database is a
    non-production mirror of the demo organisation.
    """
    settings.DEBUG = True


@pytest.fixture
def sales_account_code(syncing_enabled: None) -> str:  # noqa: ARG001 -- ordering dependency
    """The revenue code an invoice past DRAFT must carry, taken from the real tenant.

    The test database starts with no chart of accounts. Syncing is the
    application's own way of having one rather than a fixture standing in for
    it, and it refuses instead of skipping if the tenant has no such account.
    """
    list(one_way_sync_all_xero_data(entities=["accounts"], force=True))
    if not XeroAccount.objects.filter(account_name=SALES_ACCOUNT_NAME).exists():
        raise RuntimeError(
            f"The tenant has no '{SALES_ACCOUNT_NAME}' account, so no invoice can be raised."
        )
    return get_provider().get_account_code(SALES_ACCOUNT_NAME)


@pytest.fixture
def probe_company() -> Company:
    """A company created through the app's own path, so its Xero contact is real."""
    return CompanyRestService.create_company(
        {
            "name": f"{TEST_DATA_PREFIX} Residue Probe {uuid.uuid4().hex[:8]}",
            "email": "residue-integration@example.test",
            "is_account_customer": True,
            "allow_jobs": False,
        }
    )


def _raise_invoice(company: Company, account_code: str) -> Invoice:
    """Put a real SUBMITTED invoice in Xero for this company and mirror it locally.

    SUBMITTED because that is the status the app's own invoice push sends
    (apps/xero/documents/invoice.py), and it is the state the cleanup has to be
    able to remove from.
    """
    if not company.xero_contact_id:
        raise RuntimeError(f"Company {company.name} has no Xero contact to invoice")
    themes = get_provider().list_document_themes()
    if not themes:
        raise RuntimeError("The tenant has no branding theme, so no invoice can be raised.")

    today = timezone.localdate()
    result = get_provider().create_invoice(
        InvoicePayload(
            client_external_id=company.xero_contact_id,
            company_name=company.name,
            line_items=[
                DocumentLineItem(
                    description=f"{TEST_DATA_PREFIX} residue probe line",
                    quantity=Decimal("1"),
                    unit_amount=Decimal("10.00"),
                    account_code=account_code,
                )
            ],
            date=today,
            due_date=today + timedelta(days=7),
            document_theme_external_id=themes[0].external_id,
            status="SUBMITTED",
        )
    )
    if not result.success or not result.external_id or not result.number:
        raise RuntimeError(f"Xero refused the probe invoice: {result}")

    return Invoice.objects.create(
        xero_id=result.external_id,
        number=result.number,
        company=company,
        date=today,
        due_date=today + timedelta(days=7),
        total_excl_tax=Decimal("10.00"),
        tax=Decimal("1.50"),
        total_incl_tax=Decimal("11.50"),
        amount_due=Decimal("11.50"),
        xero_last_modified=timezone.now(),
        raw_json={},
    )


def _xero_invoice_status(invoice_id: str) -> str:
    api = AccountingApi(get_api_client())
    fetched = api.get_invoice(get_tenant_id(), invoice_id)
    if not fetched.invoices:
        raise AssertionError(f"Xero no longer has invoice {invoice_id}")
    status: str | None = fetched.invoices[0].status
    if status is None:
        raise AssertionError(f"Xero returned invoice {invoice_id} with no status")
    return status


def _xero_contact_status(contact_id: str) -> str:
    api = AccountingApi(get_api_client())
    fetched = api.get_contacts(get_tenant_id(), i_ds=[contact_id], include_archived=True)
    if not fetched.contacts:
        raise AssertionError(f"Xero no longer has contact {contact_id}")
    status: str | None = fetched.contacts[0].contact_status
    if status is None:
        raise AssertionError(f"Xero returned contact {contact_id} with no status")
    return status


def test_cleanup_deletes_the_invoice_then_archives_its_contact(
    probe_company: Company, sales_account_code: str
) -> None:
    """The archive can only succeed because the invoice went first — that IS the fix."""
    invoice = _raise_invoice(probe_company, sales_account_code)
    contact_id = probe_company.xero_contact_id
    assert contact_id
    assert _xero_invoice_status(str(invoice.xero_id)) == "SUBMITTED"

    call_command("e2e_cleanup", "--confirm", stdout=StringIO())

    assert _xero_invoice_status(str(invoice.xero_id)) == "DELETED"
    assert _xero_contact_status(contact_id) == "ARCHIVED"


def test_the_sweep_archives_a_contact_no_local_row_names() -> None:
    """A hard-killed run loses its database; the organisation still holds what it made."""
    api = AccountingApi(get_api_client())
    name = f"{TEST_DATA_PREFIX} Sweep Probe {secrets.token_hex(4)}"
    created = api.create_contacts(get_tenant_id(), contacts={"contacts": [Contact(name=name)]})
    assert created.contacts, "Xero returned no contact for the probe"
    contact_id: str | None = created.contacts[0].contact_id
    assert contact_id
    assert not Company.objects.filter(xero_contact_id=contact_id).exists()

    out = StringIO()
    call_command("e2e_xero_sweep", "--confirm", stdout=out)

    assert _xero_contact_status(contact_id) == "ARCHIVED"
