"""Purchase-order ETags (ADR 0003).

Opus: these three helpers live here rather than in ``purchase_order_service``
because all three PO write services need them -- the header/line update, the
delivery receipt and the allocation delete. Keeping them in
``purchase_order_service`` made ``allocation_service`` import it, which is a
cycle: ``purchase_order_service`` already imports ``allocation_service`` for
the auto-allocate path. A shared concept belongs in a shared home (ADR 0039)
rather than behind a function-local import that hides the cycle.
"""

import logging
from uuid import UUID

from apps.core.etag import (
    PreconditionFailedError,
    generate_updated_at_etag,
    if_match_satisfied,
)
from apps.purchasing.models import PurchaseOrder

logger = logging.getLogger(__name__)


def purchase_order_etag(po: PurchaseOrder) -> str:
    """Return the strong ETag for a purchase order (resource label ``po``)."""
    return generate_updated_at_etag("po", po.id, po.updated_at)


def current_purchase_order_etag(po_id: UUID) -> str | None:
    """Return the current ETag for ``po_id``, or None when it does not exist."""
    po = PurchaseOrder.objects.only("id", "updated_at").filter(id=po_id).first()
    return purchase_order_etag(po) if po else None


def require_current_etag(po: PurchaseOrder, if_match: str) -> None:
    """Raise ``PreconditionFailedError`` unless ``if_match`` names this version."""
    current = purchase_order_etag(po)
    if not if_match_satisfied(if_match, current):
        logger.warning(
            "ETag mismatch on PO %s: client sent %r, current %r", po.id, if_match, current
        )
        raise PreconditionFailedError("Purchase order modified since it was fetched.")
