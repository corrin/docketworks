"""Docketworks keeps Xero's copy of a purchase order current, without a button.

Xero holds the order so the supplier's bill has something to reconcile against.
That only works if the copy is there before the bill arrives and stays current
after — and if staying current is the operator's job to remember, forgetting it
is invisible until the accounts do not match.

Business risk covered. Nothing pushed at all before this: the only path to Xero
was two endpoints with no caller, so an order reached the supplier and never
reached Xero, and the control on paying for things nobody ordered had nothing to
match against. The sweep is what makes the guarantee hold through a refusal that
has nothing to do with our data — the day quota under its floor, a lapsed
connection, an outage, a worker that died holding the message.
"""

import uuid
from unittest.mock import patch

import pytest
from django.test import Client
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from apps.accounts.models import Staff
from apps.purchasing.tasks import PUSH_PURCHASE_ORDER_TASK as PUSH_TASK
from apps.purchasing.tasks import queue_purchase_order_push
from apps.purchasing.tests.conftest import make_po_line, make_purchase_order

pytestmark = pytest.mark.django_db

SEND = "apps.purchasing.tasks.current_app.send_task"
PUSH = "apps.xero.tasks.push_purchase_order_to_xero.delay"


class TestQueueingOnWrite:
    def test_a_submitted_order_is_pushed(
        self, django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks
    ) -> None:
        """Submitted is when Xero needs it: the bill is on its way."""
        po = make_purchase_order(status="submitted", created_by=Staff.get_automation_user())

        with patch(SEND) as send, django_capture_on_commit_callbacks(execute=True):
            queue_purchase_order_push(po)

        send.assert_called_once_with(PUSH_TASK, args=[str(po.id)])

    def test_a_draft_nobody_has_sent_is_not_pushed(
        self, django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks
    ) -> None:
        """Still ours alone; the supplier has not seen it, so no bill can arrive."""
        po = make_purchase_order(status="draft", created_by=Staff.get_automation_user())

        with patch(SEND) as send, django_capture_on_commit_callbacks(execute=True):
            queue_purchase_order_push(po)

        send.assert_not_called()

    def test_a_draft_already_in_xero_is_kept_current(
        self, django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks
    ) -> None:
        """Once a copy exists it must not drift, whatever our status says."""
        po = make_purchase_order(status="draft", created_by=Staff.get_automation_user())
        po.xero_id = uuid.uuid4()
        po.save(update_fields=["xero_id"])

        with patch(SEND) as send, django_capture_on_commit_callbacks(execute=True):
            queue_purchase_order_push(po)

        send.assert_called_once_with(PUSH_TASK, args=[str(po.id)])

    def test_an_order_we_did_not_raise_is_not_pushed_back(
        self, django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks
    ) -> None:
        """Xero owns it; sending it back would be us overwriting their record."""
        po = make_purchase_order(status="submitted", created_by=None)

        with patch(SEND) as send, django_capture_on_commit_callbacks(execute=True):
            queue_purchase_order_push(po)

        send.assert_not_called()

    def test_the_patch_endpoint_queues_the_push(
        self, client: Client, django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks
    ) -> None:
        """Through the real entry point, not the helper."""
        po = make_purchase_order(status="submitted", created_by=Staff.get_automation_user())
        make_po_line(po, quantity="1.00", unit_cost="5.00")
        etag = client.get(f"/api/purchasing/purchase-orders/{po.id}/").headers["ETag"]

        with patch(SEND) as send, django_capture_on_commit_callbacks(execute=True):
            response = client.patch(
                f"/api/purchasing/purchase-orders/{po.id}/",
                data={"reference": "confirmed"},
                content_type="application/json",
                headers={"If-Match": etag},
            )

        assert response.status_code == 200
        send.assert_called_once_with(PUSH_TASK, args=[str(po.id)])
