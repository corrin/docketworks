import uuid
import weakref
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from blinker.base import make_id
from django.test import RequestFactory, override_settings
from django.utils import timezone
from nplusone.core import listeners, signals
from nplusone.core.exceptions import NPlusOneError

from apps.accounting.models import Invoice
from apps.client.models import Client
from docketworks.nplusone import (
    StrongLazyListener,
    StrongNPlusOneMiddleware,
    install_strong_nplusone_listeners,
)


def _make_client(name: str) -> Client:
    return Client.objects.create(name=name, xero_last_modified=timezone.now())


def _make_invoice(client: Client, invoice_date: date, amount: Decimal) -> Invoice:
    return Invoice.objects.create(
        xero_id=uuid.uuid4(),
        number=f"INV-{uuid.uuid4().hex[:8]}",
        client=client,
        date=invoice_date,
        total_excl_tax=amount,
        tax=Decimal("0.00"),
        total_incl_tax=amount,
        amount_due=Decimal("0.00"),
        xero_last_modified=timezone.now(),
        raw_json={},
    )


def test_nplusone_receivers_are_strong_and_explicitly_disconnected():
    """Silences weakref cleanup noise without leaving receivers registered."""
    install_strong_nplusone_listeners()
    listener = StrongLazyListener(SimpleNamespace(notify=lambda _message: None))
    receiver_id = make_id(listener.handle_load)

    listener.setup()

    receiver = signals.load.receivers[receiver_id]
    assert not isinstance(receiver, weakref.ReferenceType)
    assert receiver == listener.handle_load

    listener.cleanup()

    assert receiver_id not in signals.load.receivers


@pytest.mark.django_db
@override_settings(
    NPLUSONE_ENABLED=True,
    NPLUSONE_RAISE=True,
    NPLUSONE_LOG=False,
)
def test_real_nplusone_still_raises_after_strong_listener_install():
    """The cleanup fix must not hide actual detector findings."""
    client = _make_client("Nplusone Client")
    _make_invoice(client, date(2026, 6, 1), Decimal("10.00"))
    _make_invoice(client, date(2026, 6, 2), Decimal("20.00"))
    middleware = StrongNPlusOneMiddleware(lambda request: None)
    request = RequestFactory().get("/nplusone-test/")

    middleware.process_request(request)
    try:
        invoices = list(Invoice.objects.order_by("number"))
        touched_names = []
        with pytest.raises(NPlusOneError, match="Potential n\\+1 query detected"):
            for invoice in invoices:
                touched_names.append(invoice.client.name)
    finally:
        middleware.process_response(request, SimpleNamespace(status_code=200))

    assert touched_names == []
    assert listeners.listeners["lazy_load"] is StrongLazyListener
