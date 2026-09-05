"""Purchase-order email composition, and the Gmail draft it becomes.

Nothing is sent: the message lands as a draft in the mailbox of whoever pressed
the button, for them to read and send. That is deliberate — an order going to a
supplier gets a human look first — and it is also what lets the order PDF ride
along, which a mailto: link could never do.
"""

import logging
from dataclasses import dataclass

from apps.core.models import CompanyDefaults
from apps.purchasing.models import PurchaseOrder

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PurchaseOrderEmail:
    """The composed message, before it becomes a draft."""

    email: str
    subject: str
    body: str


def create_purchase_order_email(
    purchase_order: PurchaseOrder,
    *,
    recipient_email: str | None = None,
    message: str | None = None,
) -> PurchaseOrderEmail:
    """Compose the supplier email for ``purchase_order``.

    ``recipient_email`` retargets the message and ``message`` is prepended to
    the body.

    Raises ``ValueError`` when the PO has no supplier, or the supplier has no
    email address — there is nothing to address the message to.
    """
    supplier = purchase_order.supplier
    if not supplier:
        raise ValueError("Purchase order must have a supplier assigned")
    if not supplier.email:
        raise ValueError(f"Supplier '{supplier.name}' has no email address configured")

    company = CompanyDefaults.get_solo()
    recipient = recipient_email or supplier.email
    subject = f"Purchase Order {purchase_order.po_number}"
    body = (
        f"Hi,\n\n"
        f"Please find attached Purchase Order #{purchase_order.po_number}.\n\n"
        f"If you have any questions about this order, please reply to this e-mail.\n\n"
        f"Thanks,\n{company.company_name}"
    )
    if message:
        body = f"{message}\n\n{body}"

    logger.info("Email prepared for purchase order %s", purchase_order.po_number)
    return PurchaseOrderEmail(email=recipient, subject=subject, body=body)
