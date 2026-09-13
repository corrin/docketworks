"""A refusal Xero embeds in a 200 is still a refusal when it reaches the operator.

The provider asks for errors inline, so a refused purchase order comes back
inside a 200 with the refusal on the element. Everything downstream classes a
result by its status code, and an element-level result once carried none: the
manager read that as 500, the mirror read 500 as an outage, and the operator
saw a successful submit of an order Xero had refused. This drives the real
endpoint, service, mirror, manager and provider with only the SDK replaced,
because a stub above the provider is exactly where the code went missing.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.test import Client

from apps.purchasing.tests.factories import make_po_line, make_purchase_order
from apps.xero.provider import XeroAccountingProvider

pytestmark = pytest.mark.django_db

MIRROR = "apps.purchasing.services.accounting_mirror.get_provider"


def test_an_embedded_refusal_fails_the_state_change(api: Client) -> None:
    po = make_purchase_order(status="draft")
    make_po_line(po, quantity="1.00", unit_cost="5.00")
    provider = XeroAccountingProvider()
    sdk = Mock()
    sdk.update_or_create_purchase_orders.return_value = SimpleNamespace(
        purchase_orders=[
            SimpleNamespace(
                purchase_order_id=str(uuid4()),
                validation_errors=[SimpleNamespace(message="Contact is archived")],
            )
        ]
    )
    url = f"/api/purchasing/purchase-orders/{po.pk}/"
    etag = api.get(url).headers["ETag"]

    with (
        patch(MIRROR, return_value=provider),
        patch("apps.xero.documents.base.get_provider", return_value=provider),
        patch.object(provider, "_get_api", return_value=(sdk, str(uuid4()))),
        patch.object(provider, "get_account_code", return_value="300"),
    ):
        response = api.patch(
            url,
            data={"status": "submitted"},
            content_type="application/json",
            headers={"If-Match": etag},
        )

    assert response.status_code == 400, response.content
    assert sdk.update_or_create_purchase_orders.call_count == 1
    po.refresh_from_db()
    assert po.status == "draft"
    assert po.xero_push_due is False, (
        "a refusal the operator must fix is not owed to the hourly sync"
    )
