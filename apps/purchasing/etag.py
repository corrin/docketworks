"""Purchase Order ETag generation."""

from __future__ import annotations

from apps.purchasing.models import PurchaseOrder
from apps.workflow.etag import generate_updated_at_etag


def generate_po_etag(po: PurchaseOrder) -> str:
    """Generate a strong ETag for a Purchase Order."""
    return generate_updated_at_etag("po", po.id, po.updated_at)
