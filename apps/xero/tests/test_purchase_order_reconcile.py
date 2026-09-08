"""The sweep that keeps Xero's copy of a purchase order current.

The push queued when an order is written is an optimisation; this is the
guarantee. Xero refuses work for reasons that have nothing to do with our data —
the day quota under its floor, a lapsed connection, an outage, a worker that
died holding the message — and every one of those resolves on its own. Without
a sweep, "it resolves itself" means the order is simply never sent, and the
supplier's bill arrives with nothing to reconcile against.

It lives here rather than beside the queueing test because the task does: a
domain app may not import an integration, and pushing to Xero is Xero's work.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.accounting.types import DocumentResult, POPayload
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.purchasing.etag import purchase_order_etag
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services.purchase_order_service import update_purchase_order
from apps.purchasing.tests.conftest import make_po_line, make_purchase_order
from apps.xero.tasks import reconcile_purchase_orders_to_xero
from apps.xero.tests.conftest import make_po_manager, make_po_provider

pytestmark = pytest.mark.django_db

PUSH = "apps.xero.tasks.push_purchase_order_to_xero.delay"


class TestTheSweep:
    """What makes a refused push heal instead of needing to be noticed."""

    def _behind(self, status: str) -> PurchaseOrder:
        """An order that reached Xero once and was edited here afterwards.

        The stamp has to be older than ``updated_at`` for that to be the state
        under test. Setting ``xero_last_synced`` instead left every case in
        this file on the ``isnull`` branch, so the predicate could have
        regressed to the column that is written by every inbound pull and
        nothing here would have gone red.
        """
        po = make_purchase_order(status=status, created_by=Staff.get_automation_user())
        PurchaseOrder.objects.filter(id=po.id).update(
            xero_agreed_at=timezone.now() - timedelta(hours=1)
        )
        po.refresh_from_db()
        assert po.xero_agreed_at is not None, "the stale branch, not the null one"
        assert po.xero_agreed_at < po.updated_at
        return po

    def test_an_order_already_in_step_with_xero_is_left_alone(self) -> None:
        """The negative twin: without it, a predicate that sweeps everything passes."""
        po = make_purchase_order(status="submitted", created_by=Staff.get_automation_user())
        PurchaseOrder.objects.filter(id=po.id).update(
            xero_agreed_at=timezone.now() + timedelta(minutes=1)
        )

        with patch(PUSH) as delay:
            reconcile_purchase_orders_to_xero()

        assert str(po.id) not in [call.args[0] for call in delay.call_args_list]

    def test_an_edit_that_never_reached_xero_is_swept_up(self) -> None:
        po = self._behind("submitted")

        with patch(PUSH) as delay:
            reconcile_purchase_orders_to_xero()

        assert str(po.id) in [call.args[0] for call in delay.call_args_list]

    def test_an_order_that_never_got_there_at_all_is_swept_up(self) -> None:
        """The case a lost message or a dead worker leaves behind."""
        po = make_purchase_order(status="submitted", created_by=Staff.get_automation_user())

        with patch(PUSH) as delay:
            reconcile_purchase_orders_to_xero()

        assert str(po.id) in [call.args[0] for call in delay.call_args_list]

    def test_drafts_and_cancelled_orders_are_left_alone(self) -> None:
        """A draft is unsent; a cancelled one Xero would refuse anyway."""
        draft = self._behind("draft")
        deleted = self._behind("deleted")

        with patch(PUSH) as delay:
            reconcile_purchase_orders_to_xero()

        pushed = [call.args[0] for call in delay.call_args_list]
        assert str(draft.id) not in pushed
        assert str(deleted.id) not in pushed

    def test_an_order_we_did_not_raise_is_left_alone(self) -> None:
        po = make_purchase_order(status="submitted", created_by=None)
        PurchaseOrder.objects.filter(id=po.id).update(
            xero_last_synced=timezone.now() - timedelta(hours=1)
        )

        with patch(PUSH) as delay:
            reconcile_purchase_orders_to_xero()

        assert str(po.id) not in [call.args[0] for call in delay.call_args_list]

    def test_a_quota_floor_defers_rather_than_failing(self) -> None:
        """The floor exists so automated work yields; the next sweep retries."""
        po = self._behind("submitted")

        with (
            patch("apps.xero.tasks.quota_floor_breached", return_value=True),
            patch(PUSH) as delay,
        ):
            reconcile_purchase_orders_to_xero()

        assert str(po.id) not in [call.args[0] for call in delay.call_args_list]


@pytest.fixture
def pushable_po(office_staff: Staff) -> PurchaseOrder:
    supplier = Company.objects.create(
        name="Push supplier", xero_contact_id=str(uuid4()), xero_last_modified=timezone.now()
    )
    po = make_purchase_order(
        supplier=supplier, created_by=office_staff, status="submitted", reference="Original"
    )
    make_po_line(po)
    return po


def _edit(po: PurchaseOrder, staff: Staff, reference: str) -> PurchaseOrder:
    """Save an actual edit whose queued push is unavailable."""
    current = PurchaseOrder.objects.get(pk=po.pk)
    with patch("apps.purchasing.services.purchase_order_service.queue_purchase_order_push"):
        return update_purchase_order(
            po.id, {"reference": reference}, staff=staff, if_match=purchase_order_etag(current)
        )


def _is_swept(po: PurchaseOrder) -> bool:
    """Ask the actual reconciliation selector whether the order needs a retry."""
    with patch(PUSH) as delay:
        reconcile_purchase_orders_to_xero()
    return str(po.id) in [call.args[0] for call in delay.call_args_list]


class TestPushAgreement:
    """GPT: a provider response may only acknowledge the local version it contained."""

    @pytest.mark.parametrize("already_linked", [False, True])
    def test_an_inflight_edit_is_reconciled(
        self,
        pushable_po: PurchaseOrder,
        office_staff: Staff,
        xero_tenant_id: str,
        already_linked: bool,
    ) -> None:
        po = pushable_po
        external_id = str(uuid4())
        if already_linked:
            po.xero_id = external_id
            po.xero_agreed_at = po.updated_at
            po.save(update_fields=["xero_id", "xero_agreed_at"])
        agreement_before = po.xero_agreed_at
        success = DocumentResult(
            success=True, external_id=external_id, online_url=f"https://go.xero.com/{external_id}"
        )
        provider = make_po_provider(success)
        payloads: list[POPayload] = []

        def edit_during_request(payload: POPayload) -> DocumentResult:
            payloads.append(payload)
            _edit(po, office_staff, "Confirmed while sending")
            return success

        provider.create_purchase_order.side_effect = edit_during_request
        provider.update_purchase_order.side_effect = edit_during_request
        assert make_po_manager(po, provider).sync_to_xero()["success"]
        po.refresh_from_db()
        assert payloads[0].reference == "Original"
        assert str(po.xero_id) == external_id
        assert po.xero_tenant_id == xero_tenant_id
        assert po.online_url == success.online_url
        assert po.xero_agreed_at == agreement_before
        assert _is_swept(po), "an edit missing from the payload was declared delivered"

        provider.update_purchase_order.side_effect = None
        etag_before = purchase_order_etag(po)
        assert make_po_manager(po, provider).sync_to_xero()["success"]
        assert (
            provider.update_purchase_order.call_args.args[0].reference == "Confirmed while sending"
        )
        po.refresh_from_db()
        assert purchase_order_etag(po) == etag_before
        assert not _is_swept(po)

    @pytest.mark.parametrize("already_linked", [False, True])
    def test_a_successful_unchanged_push_agrees_without_changing_the_etag(
        self,
        pushable_po: PurchaseOrder,
        xero_tenant_id: str,
        already_linked: bool,
    ) -> None:
        po = pushable_po
        external_id = str(uuid4())
        if already_linked:
            po.xero_id = external_id
            po.save(update_fields=["xero_id"])
        etag_before = purchase_order_etag(po)
        result = DocumentResult(
            success=True, external_id=external_id, online_url=f"https://go.xero.com/{external_id}"
        )
        assert make_po_manager(po, make_po_provider(result)).sync_to_xero()["success"]
        po.refresh_from_db()
        assert str(po.xero_id) == external_id
        assert po.xero_tenant_id == xero_tenant_id
        assert po.online_url == result.online_url
        assert po.xero_agreed_at is not None and po.xero_agreed_at >= po.updated_at
        assert purchase_order_etag(po) == etag_before
        assert not _is_swept(po)

    def test_an_older_response_cannot_hide_a_subsequent_unsent_edit(
        self,
        pushable_po: PurchaseOrder,
        office_staff: Staff,
    ) -> None:
        po = pushable_po
        po.xero_id = str(uuid4())
        po.save(update_fields=["xero_id"])
        success = DocumentResult(success=True, external_id=str(po.xero_id))
        provider = make_po_provider(success)
        agreements = []

        def complete_newer_push_first(payload: POPayload) -> DocumentResult:
            assert payload.reference == "Original"
            newer = _edit(po, office_staff, "Newer sent edit")
            assert make_po_manager(newer, make_po_provider(success)).sync_to_xero()["success"]
            newer.refresh_from_db()
            agreements.append(newer.xero_agreed_at)
            _edit(newer, office_staff, "Newest unsent edit")
            return success

        provider.update_purchase_order.side_effect = complete_newer_push_first
        assert make_po_manager(po, provider).sync_to_xero()["success"]
        po.refresh_from_db()
        assert po.xero_agreed_at == agreements[0]
        assert po.reference == "Newest unsent edit"
        assert _is_swept(po)

    def test_a_refused_push_leaves_the_edit_eligible_for_retry(
        self, pushable_po: PurchaseOrder
    ) -> None:
        po = pushable_po
        agreement_before = po.xero_agreed_at
        provider = make_po_provider(
            DocumentResult(success=False, error="Quota exhausted", status_code=429)
        )
        assert not make_po_manager(po, provider).sync_to_xero()["success"]
        po.refresh_from_db()
        assert po.xero_agreed_at == agreement_before
        assert _is_swept(po)


def test_response_cannot_attach_an_old_line_id_to_a_replacement(
    pushable_po: PurchaseOrder, office_staff: Staff
) -> None:
    po = pushable_po
    original = po.po_lines.get()
    response_id = uuid4()
    external_id = str(uuid4())
    success = DocumentResult(
        success=True,
        external_id=external_id,
        raw_response={
            "line_items": [
                {"description": original.xero_description, "line_item_id": str(response_id)}
            ]
        },
    )
    provider = make_po_provider(success)

    def replace_while_sending(payload: POPayload) -> DocumentResult:
        assert payload.line_items[0].description == original.xero_description
        with patch("apps.purchasing.services.purchase_order_service.queue_purchase_order_push"):
            update_purchase_order(
                po.id,
                {
                    "lines_to_delete": [original.id],
                    "lines": [
                        {
                            "description": original.description,
                            "quantity": Decimal("2"),
                            "unit_cost": Decimal("19"),
                        }
                    ],
                },
                staff=office_staff,
                if_match=purchase_order_etag(po),
            )
        return success

    provider.create_purchase_order.side_effect = replace_while_sending
    assert make_po_manager(po, provider).sync_to_xero()["success"]
    replacement = po.po_lines.get()
    po.refresh_from_db()
    assert replacement.id != original.id
    assert replacement.xero_line_item_id is None
    assert po.xero_agreed_at is None
    assert str(po.xero_id) == external_id
    assert replacement.unit_cost == Decimal("19")


def test_push_snapshot_refreshes_header_and_lines_together(
    pushable_po: PurchaseOrder, office_staff: Staff
) -> None:
    po = pushable_po
    provider = make_po_provider(DocumentResult(success=True, external_id=str(uuid4())))
    manager = make_po_manager(po, provider)
    original = po.po_lines.get()
    with patch("apps.purchasing.services.purchase_order_service.queue_purchase_order_push"):
        updated = update_purchase_order(
            po.id,
            {"reference": "New header", "lines": [{"id": original.id, "unit_cost": Decimal("19")}]},
            staff=office_staff,
            if_match=purchase_order_etag(po),
        )
    assert manager.sync_to_xero()["success"]
    payload = provider.create_purchase_order.call_args.args[0]
    assert payload.reference == "New header"
    assert payload.line_items[0].unit_amount == Decimal("19")
    po.refresh_from_db()
    assert po.updated_at == updated.updated_at
    assert po.xero_agreed_at is not None and po.xero_agreed_at >= po.updated_at


def test_duplicate_descriptions_receive_distinct_response_line_ids(
    pushable_po: PurchaseOrder,
) -> None:
    po = pushable_po
    original = po.po_lines.get()
    make_po_line(
        po,
        description=original.description,
        quantity=str(original.quantity),
        unit_cost=str(original.unit_cost),
    )
    response_ids = [uuid4(), uuid4()]
    success = DocumentResult(
        success=True,
        external_id=str(uuid4()),
        raw_response={
            "line_items": [
                {"description": original.xero_description, "line_item_id": str(line_id)}
                for line_id in response_ids
            ]
        },
    )
    assert make_po_manager(po, make_po_provider(success)).sync_to_xero()["success"]
    assert set(po.po_lines.values_list("xero_line_item_id", flat=True)) == set(response_ids)
