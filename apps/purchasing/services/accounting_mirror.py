"""Telling the accounting system about a purchase order, and when.

Xero holds a copy of the order for one reason: so the supplier's bill has
something to link against. That fixes the schedule as well as the purpose.
Bills arrive overnight, so nothing here is urgent, and the only moments Xero
needs to hear about are the order leaving draft — the first point a bill can
come back — and the receipt that settles its total.

A field edit is not one of those moments. The workspace saves each field as its
own PATCH, so pushing per write cost 9 calls to build an eight-line order and 33
in a normal session, each a round trip with the operator waiting.

Its own module because both write paths need it and neither may import the
other: ``purchase_order_service`` imports ``receive_outstanding_order`` from
``delivery_receipt_service``, so the send cannot live in either.
"""

import logging
import re

from django.db import transaction

from apps.accounting.registry import get_provider
from apps.accounts.models import Staff
from apps.core.errors import InvalidInputError, UpstreamRefusedError
from apps.core.models import CompanyDefaults
from apps.purchasing.models import PurchaseOrder

logger = logging.getLogger(__name__)


def is_locally_raised(po: PurchaseOrder) -> bool:
    """Whether Docketworks raised this order, rather than Xero.

    Both systems raise purchase orders and each numbers its own, so the number
    is what says whose it is: ours match the instance's ``po_prefix``, the same
    pattern ``get_last_purchase_order_number`` counts under.

    Opus: ``created_by`` asks a question that looks identical and is not. It
    went unrecorded until 2026-01-09, so 419 of the 825 orders we raised carry
    none, and reading ownership from it hands Xero the right to overwrite every
    one of them on the next pull. Measured 2026-09-13 against a production
    restore; no order outside the prefix has a ``created_by`` at all.

    ``po_prefix`` is therefore not an ordinary setting. Changing it reclassifies
    every order raised under the old one as Xero's, which is the same defect the
    paragraph above describes, reached by an admin edit instead of a null column.
    """
    prefix = CompanyDefaults.get_solo().po_prefix
    return re.fullmatch(rf"{re.escape(prefix)}\d+", po.po_number) is not None


def mirror_purchase_order(po: PurchaseOrder, staff: Staff) -> None:
    """Make the accounting system's copy match ours, or say why it cannot.

    The refusal is typed rather than passed through as one status: a rejected
    order is the operator's to fix, while a quota or an outage says the same
    call would succeed later, and a caller that cannot tell them apart either
    retries a fault forever or abandons a call that was only postponed.
    """
    if not is_locally_raised(po):
        # Ownership first: Xero raised this one and masters it, so our copy is
        # the mirror and has nothing to publish, and its shape is not ours to
        # refuse. The next pull is what settles it.
        return
    # No quota-floor check here, deliberately: the floor exists so automated
    # work yields to interactive use, and a state change an operator just made
    # is the interactive use. The hourly catch-up stage is the automated side,
    # and that is where the floor is checked (apps/xero/sync.py).
    if po.supplier is None:
        # The mirror is a document addressed to a supplier, so there is nothing
        # to send. Raised here rather than left to the provider, which would
        # surface a missing supplier as a 500.
        raise InvalidInputError("A purchase order needs a supplier before it can reach Xero")
    result = get_provider().push_purchase_order(po, staff)
    if result.success:
        return
    message = result.error or "The accounting system refused this purchase order."
    if result.status_code == 400:
        raise InvalidInputError(message)
    raise UpstreamRefusedError(message)


def send_state_change(po: PurchaseOrder, staff: Staff) -> None:
    """Spend the call now, or leave the order owing one to the hourly sync.

    The order's row is held for the duration of the call, vendor round trip
    included, so two pushes of one order cannot cross at Xero and the
    acknowledgement belongs to the version that stands. The operator's save and
    the receipt already hold it across their own push, so taking it here costs
    them nothing (a re-take on the same connection is a savepoint) and is new
    only for the hourly stage. Acknowledging by version without the lock was
    rejected: a stale push completing after a newer one still reached Xero
    last, with nothing left owed.

    A validation refusal is raised: a supplier with no Xero contact, or an
    order Xero will not accept, is the operator's to fix and no later attempt
    helps, so the state change fails while they are still looking at it.

    A vendor refusal is not. Blocking a status change because Xero is having a
    bad afternoon would make the operator wait on a system they cannot see, for
    a copy nothing reads until a bill arrives overnight. ``xero_push_due`` is
    still set, so the sync stage sends it inside the hour.
    """
    with transaction.atomic():
        owed = (
            PurchaseOrder.objects.select_for_update(of=("self",))
            .filter(pk=po.pk)
            .values_list("xero_push_due", flat=True)
            .get()
        )
        if not owed:
            # A push that held the row before this one acknowledged the order;
            # sending it again would spend a Xero call on the same content.
            po.xero_push_due = False
            return
        try:
            mirror_purchase_order(po, staff)
        # deliberate-swallow: converted to "still owed", which is a state the
        # hourly sync acts on, rather than an error the operator can do anything
        # about. Re-raising would fail a local write over a vendor's availability.
        except UpstreamRefusedError:
            logger.warning(
                "Xero deferred purchase order %s; left owed for the hourly sync", po.po_number
            )
            return
        PurchaseOrder.objects.filter(pk=po.pk).update(xero_push_due=False)
    po.xero_push_due = False
