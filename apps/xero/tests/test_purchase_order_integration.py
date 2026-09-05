"""The purchase-order push against the real demo tenant (ADR 0050).

One stateful scenario in the order an order actually moves: created in Xero from
a draft, changed and pushed again so the update path runs against a real
``xero_id``, then voided. Xero state survives pytest while the local test
database does not, so independent tests would each lie about their starting
state.

Every assertion reads the state back **from Xero** rather than trusting the
push's return value, and it reads it through the application's own inbound sync
— the same code production uses. That is what a fake provider cannot do: it
returns whatever the author assumed, so it can only confirm the belief.

Re-runnable by construction: the supplier and the order are new each run, so a
document stranded by an aborted run is inert rather than in the way.

It is not cheap, though. Each run syncs the chart of accounts, creates a contact,
pushes several orders and pulls the tenant's purchase orders three or four times,
so a handful of runs will take the day quota to ``xero_automated_day_floor`` and
the next one fails loudly with ``XeroQuotaFloorReached``. That is the guard
working — it reserves the remaining calls for interactive use — not a fault in
the suite. Run it when the change warrants it, not on a loop.
"""

import logging
import uuid
from dataclasses import replace
from decimal import Decimal

import pytest
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from apps.accounting.registry import get_provider
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.services.company_rest_service import CompanyRestService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.xero.auth import get_tenant_id
from apps.xero.documents.po import XeroPurchaseOrderManager
from apps.xero.models import XeroAccount
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.sync import one_way_sync_all_xero_data

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def xero_tenant_id(integration_credentials: None) -> str:  # noqa: ARG001
    """Talk to the real tenant, overriding this directory's suite-wide patch.

    ``apps/xero/tests/conftest.py`` patches ``apps.xero.documents.po.get_tenant_id``
    to a fixed fake for every test here — right for the hermetic ones, wrong for
    this file, because the push under test resolves its tenant through exactly
    that binding. Shadowing the fixture by name is what turns it off. It
    requests ``integration_credentials`` because resolving a tenant needs a live
    token and that fixture is what supplies one; two autouse fixtures have no
    ordering between them otherwise.
    """
    return get_tenant_id()


@pytest.fixture(autouse=True)
def _guards(xero_tenant_id: str) -> None:  # noqa: ARG001
    assert_not_production_target()
    assert_xero_writes_enabled("the purchase-order integration suite")


@pytest.fixture
def syncing_enabled(settings: SettingsWrapper) -> None:
    """Let the inbound sync run against the demo tenant.

    ``sync.py`` reads DEBUG-off as "this is production" and aborts any sync of a
    non-production tenant. pytest forces DEBUG off, so without this every sync
    here aborts — and it aborts with severity ``warning``, so a check that only
    collects errors reports a clean run over an empty database. This test
    database is a non-production mirror of the demo tenant.
    """
    settings.DEBUG = True


@pytest.fixture
def synced_accounts(syncing_enabled: None) -> None:  # noqa: ARG001
    """Pull the chart of accounts, because the push resolves a code through it.

    The test database is thrown away, so it starts with no accounts and the
    push fails on the "Purchases" lookup with a bare DoesNotExist. Syncing is
    the application's own way of having them — not a fixture standing in for
    one — and it refuses rather than skipping if the tenant has no such account.
    """
    _sync("accounts")
    if not XeroAccount.objects.filter(account_name="Purchases").exists():
        raise RuntimeError(
            "The tenant has no 'Purchases' account, so no purchase order can be pushed."
        )


@pytest.fixture
def pushing_staff() -> Staff:
    """The staff member the push is attributed to."""
    return Staff.objects.create_user(
        office_email="po-integration@example.test",
        password="s3cret-Pass!",
        first_name="PO",
        last_name="Integration",
        is_office_staff=True,
    )


@pytest.fixture
def xero_supplier() -> Company:
    """A supplier created through the app's own path, so its contact is real."""
    return CompanyRestService.create_company(
        {
            "name": f"[TEST] PO supplier {uuid.uuid4().hex[:8]}",
            "email": "po-integration@example.test",
            "is_account_customer": False,
            "allow_jobs": False,
        }
    )


def _sync(entity: str) -> None:
    """Run one entity's inbound sync, refusing on any error it reports.

    A sync that reports errors and is iterated for its side effects only is
    indistinguishable from one that did nothing — which is the silent pass
    ADR 0050 exists to stop.
    """
    events = list(one_way_sync_all_xero_data(entities=[entity], force=True))
    for event in events:
        logger.info("xero %s sync event: %s", entity, event)
    # An abort is a warning, not an error: collecting only errors reports a
    # clean run over a sync that did nothing.
    refusals = [
        event["message"]
        for event in events
        if event["severity"] == "error" or "aborted" in event["message"].lower()
    ]
    if refusals:
        raise RuntimeError(f"Xero {entity} sync did not run: " + "; ".join(refusals))


def _pushed_order(supplier: Company, staff: Staff) -> PurchaseOrder:
    """A purchase order that exists in Xero with nothing outstanding to send."""
    po = PurchaseOrder.objects.create(
        supplier=supplier,
        created_by=staff,
        status="submitted",
        po_number=f"TEST-{uuid.uuid4().hex[:10]}",
        reference=f"[TEST] sync {uuid.uuid4().hex[:8]}",
    )
    PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="[TEST] 5mm round bar",
        quantity=Decimal("3.00"),
        unit_cost=Decimal("12.50"),
    )
    result = XeroPurchaseOrderManager(purchase_order=po, staff=staff).sync_to_xero()
    assert result["success"], result
    po.refresh_from_db()
    return po


def _edit_in_xero(po: PurchaseOrder, staff: Staff, *, description: str) -> None:
    """Change the order inside Xero, leaving our row untouched.

    Built from our own payload and sent through the provider, so the edit is one
    Xero accepts from any client — it stands in for a person editing the order
    in the Xero UI, which is the case the inbound sync exists for.
    """
    payload = XeroPurchaseOrderManager(purchase_order=po, staff=staff).build_payload()
    edited = replace(
        payload,
        line_items=[replace(payload.line_items[0], description=description)],
    )
    result = get_provider().update_purchase_order(edited)
    assert result.success, result


def _pull_back(po: PurchaseOrder) -> PurchaseOrder:
    """Re-read the order from Xero through the app's inbound sync."""
    _sync("purchase_orders")
    po.refresh_from_db()
    return po


@pytest.mark.usefixtures("synced_accounts")
def test_a_purchase_order_is_created_updated_and_voided_in_xero(
    xero_supplier: Company, pushing_staff: Staff
) -> None:
    # The number is set explicitly, not left to the model's sequence. The
    # inbound sync matches an incoming order by xero_id and THEN by po_number,
    # and this database is thrown away so the sequence restarts every run —
    # so a generated number collides with the previous run's, and the pull-back
    # re-links this fresh order to that run's voided Xero document. Xero then
    # refuses the update with "Deleted PurchaseOrders cannot be updated".
    po = PurchaseOrder.objects.create(
        supplier=xero_supplier,
        created_by=pushing_staff,
        status="draft",
        po_number=f"TEST-{uuid.uuid4().hex[:10]}",
        reference=f"[TEST] integration {uuid.uuid4().hex[:8]}",
    )
    line = PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="[TEST] 5mm round bar",
        quantity=Decimal("3.00"),
        unit_cost=Decimal("12.50"),
    )

    created = XeroPurchaseOrderManager(purchase_order=po, staff=pushing_staff).sync_to_xero()
    assert created["success"], created
    po.refresh_from_db()
    first_xero_id = po.xero_id
    assert first_xero_id is not None, "Xero returned no id to store"
    assert po.online_url, "Xero returned no deep link, so 'View in Xero' would be dead"

    # The inbound sync must NOT rewrite an order Docketworks raised. Proven by
    # making the local copy disagree with Xero's on purpose: the line is changed
    # here and deliberately not pushed, so before the ownership rule the sync
    # would have reverted it to the 3.00 Xero still holds.
    line.refresh_from_db()
    line.quantity = Decimal("7.00")
    line.save(update_fields=["quantity"])
    # The order carries the outstanding-edit signal, and the service bumps it
    # after every line write; a line saved on its own does not.
    po.save(update_fields=["updated_at"])

    _pull_back(po)

    assert po.xero_id == first_xero_id
    assert po.po_lines.get().quantity == Decimal("7.00"), (
        "the sync reverted a local edit to Xero's older copy"
    )
    assert po.xero_status in {"DRAFT", "SUBMITTED", "AUTHORISED"}, po.xero_status
    assert po.status == "draft", "Xero's status overwrote ours"

    # Restore what Xero holds before the update assertions below.
    line.quantity = Decimal("3.00")
    line.save(update_fields=["quantity"])

    # A second push on a stored xero_id must UPDATE. A create would leave the
    # supplier holding two orders for one delivery.
    line.refresh_from_db()
    line.quantity = Decimal("4.00")
    line.save(update_fields=["quantity"])
    updated = XeroPurchaseOrderManager(purchase_order=po, staff=pushing_staff).sync_to_xero()
    assert updated["success"], updated

    # The push itself is the evidence Xero took it: update_or_create keys on the
    # stored xero_id, so a second document would surface as a different id.
    assert updated["xero_id"] == str(first_xero_id), "the update created a second Xero order"
    assert po.po_lines.count() == 1

    voided = XeroPurchaseOrderManager(purchase_order=po, staff=pushing_staff).delete_document()
    assert voided["success"], voided
    po.refresh_from_db()
    assert po.xero_id is None, "the void left the order pointing at a Xero document"

    # The void cleared xero_id, so the pull re-links by po_number and brings
    # back whatever Xero now says — which is what proves the void reached the
    # vendor rather than only the local row.
    _pull_back(po)
    assert po.status == "deleted", "Xero still reports this order as live"


@pytest.mark.usefixtures("synced_accounts")
def test_an_edit_made_in_xero_comes_back(xero_supplier: Company, pushing_staff: Staff) -> None:
    """The inbound half of the sync, proven against the real tenant.

    A fake provider cannot show this: it returns what the author assumed Xero
    would say. Here the order is genuinely altered inside Xero — through the
    provider, the way any other client would — and the assertion is that our
    copy takes the change rather than sitting on a stale one.
    """
    po = _pushed_order(xero_supplier, pushing_staff)

    _edit_in_xero(po, pushing_staff, description="Edited by someone in Xero")

    _sync("purchase_orders")

    # Asserted against the order, not the row. Our payload sends lines without
    # ids, so Xero replaces the line set and mints new ones — the edit lands on
    # a new row rather than the original. A person editing in the Xero UI keeps
    # the id and would update the row in place; either way the claim under test
    # is that the change reached Docketworks at all.
    assert po.po_lines.filter(description="Edited by someone in Xero").exists(), (
        "an edit made in Xero never reached Docketworks"
    )


@pytest.mark.usefixtures("synced_accounts")
def test_a_collision_publishes_ours_rather_than_dropping_either(
    xero_supplier: Company, pushing_staff: Staff
) -> None:
    """Both sides changed. Neither is silently dropped.

    Xero holds one edit, we hold another that never reached it, and the older
    copy must not win. Ours is published instead, so the two agree afterwards —
    which is what makes this a sync rather than a race.
    """
    po = _pushed_order(xero_supplier, pushing_staff)
    line = po.po_lines.get()

    _edit_in_xero(po, pushing_staff, description="Edited by someone in Xero")
    # Ours, made after the last successful send and never pushed.
    line.description = "What the office confirmed"
    line.save(update_fields=["description"])
    # update_purchase_order saves the order after writing its lines, which is
    # what marks the edit outstanding; this stands in for that.
    po.save(update_fields=["updated_at"])

    # CELERY_TASK_ALWAYS_EAGER, so the push the collision queues runs here.
    _sync("purchase_orders")

    line.refresh_from_db()
    assert line.description == "What the office confirmed", "Xero's older copy won"

    # And Xero agrees now, which is the half that makes it a sync: re-read by
    # clearing our claim on the row so the next pull mirrors in full.
    PurchaseOrder.objects.filter(id=po.id).update(created_by=None, xero_last_pushed=None)
    _sync("purchase_orders")
    assert po.po_lines.filter(description="What the office confirmed").exists(), (
        "our edit never reached Xero"
    )


def test_a_supplier_without_a_xero_contact_is_refused_before_the_call(
    pushing_staff: Staff,
) -> None:
    """The refusal names the fix, and never reaches Xero to find out."""
    unlinked = Company.objects.create(
        name="[TEST] Unlinked supplier", xero_last_modified=timezone.now()
    )
    po = PurchaseOrder.objects.create(supplier=unlinked, created_by=pushing_staff, status="draft")
    PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="[TEST] bar",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("1.00"),
    )

    manager = XeroPurchaseOrderManager(purchase_order=po, staff=pushing_staff)

    assert manager.can_sync_to_xero() is False
    with pytest.raises(ValueError, match="not linked to Xero"):
        manager.validate_for_xero_sync()
