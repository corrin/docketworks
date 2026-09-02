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
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.conftest import make_purchase_order
from apps.xero.tasks import reconcile_purchase_orders_to_xero

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
