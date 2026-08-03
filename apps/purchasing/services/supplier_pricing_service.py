"""Supplier price-list status and product-parsing-mapping review.

The read-only half of the supplier-pricing surface, ported from v1's
``SupplierPriceStatusAPIView``, ``ProductMappingListView`` and
``ProductMappingValidateView``.

What produces the rows these endpoints review now lives in the quoting slice:
``apps.quoting.services.product_parser`` (LLM parsing and the mapping table) and
``apps.quoting.scrapers`` (supplier portal ingestion). v1's PDF price-list
upload is still unported — see ``apps.quoting.services.price_extraction`` for
that seam.

The mapping → ``SupplierProduct.parsed_*`` back-flow is NOT written here. v1 had
that column list twice — in ``ProductMappingValidateView`` and again in
``product_parser.populate_all_mappings_with_llm`` — so v2 has one
implementation, ``product_parser.apply_mapping_to_products``, and this module
calls it (ADR 0039).
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.quoting.models import ProductParsingMapping, SupplierPriceList, SupplierProduct
from apps.quoting.services.product_parser import apply_mapping_to_products

logger = logging.getLogger(__name__)


class SupplierPriceStatusItemData(TypedDict):
    """v1 SupplierPriceStatusItemSerializer row."""

    supplier_id: UUID
    supplier_name: str
    last_uploaded_at: datetime | None
    file_name: str | None
    total_products: int | None
    changes_last_update: int | None


def _price_list_change_count(latest_id: UUID, previous_id: UUID) -> int:
    """Count product keys added or removed between two price lists."""
    latest_keys = set(
        SupplierProduct.objects.filter(price_list_id=latest_id).values_list("item_no", "variant_id")
    )
    previous_keys = set(
        SupplierProduct.objects.filter(price_list_id=previous_id).values_list(
            "item_no", "variant_id"
        )
    )
    return len(latest_keys - previous_keys) + len(previous_keys - latest_keys)


def supplier_price_status() -> list[SupplierPriceStatusItemData]:
    """Report the latest price upload per supplier, with a change estimate.

    v1 annotated the newest upload onto the Company queryset with subqueries
    AND then re-read the same price lists row by row; the per-supplier read is
    the one that must happen (it needs the previous list too), so v2 keeps only
    that and drops the duplicate subqueries.
    """
    suppliers = Company.objects.filter(
        id__in=SupplierPriceList.objects.values("supplier_id").distinct()
    ).order_by("name")

    items: list[SupplierPriceStatusItemData] = []
    for supplier in suppliers:
        price_lists = list(
            SupplierPriceList.objects.filter(supplier_id=supplier.id)
            .order_by("-uploaded_at")
            .values_list("id", "file_name", "uploaded_at")
        )
        total_products: int | None = None
        changes_last_update: int | None = None
        last_uploaded_at: datetime | None = None
        file_name: str | None = None
        if price_lists:
            _latest_id, file_name, last_uploaded_at = price_lists[0]
            total_products = SupplierProduct.objects.filter(supplier_id=supplier.id).count()
            if len(price_lists) > 1:
                changes_last_update = _price_list_change_count(price_lists[0][0], price_lists[1][0])
        items.append(
            {
                "supplier_id": supplier.id,
                "supplier_name": supplier.name,
                "last_uploaded_at": last_uploaded_at,
                "file_name": file_name,
                "total_products": total_products,
                "changes_last_update": changes_last_update,
            }
        )
    return items


def list_product_mappings() -> tuple[list[ProductParsingMapping], int, int]:
    """Return (mappings, validated_count, unvalidated_count), unvalidated first."""
    unvalidated = list(
        ProductParsingMapping.objects.filter(is_validated=False).order_by("-created_at")
    )
    validated = list(
        ProductParsingMapping.objects.filter(is_validated=True).order_by("-validated_at")
    )
    mappings = unvalidated + validated
    for mapping in mappings:
        mapping.update_xero_status()
    return mappings, len(validated), len(unvalidated)


class ProductMappingValidateData(TypedDict, total=False):
    """The mapping fields an operator may correct while validating."""

    mapped_item_code: str | None
    mapped_description: str | None
    mapped_metal_type: str | None
    mapped_alloy: str | None
    mapped_specifics: str | None
    mapped_dimensions: str | None
    mapped_unit_cost: Decimal | None
    mapped_price_unit: str | None
    validation_notes: str | None


def validate_product_mapping(
    mapping: ProductParsingMapping, data: ProductMappingValidateData, staff: Staff
) -> int:
    """Mark a mapping validated and back-flow its values onto its products.

    Returns the number of SupplierProduct rows updated.
    """
    mapping.is_validated = True
    mapping.validated_by = staff
    mapping.validated_at = timezone.now()
    if "mapped_item_code" in data:
        mapping.mapped_item_code = data["mapped_item_code"]
    if "mapped_description" in data:
        mapping.mapped_description = data["mapped_description"]
    if "mapped_metal_type" in data:
        mapping.mapped_metal_type = data["mapped_metal_type"]
    if "mapped_alloy" in data:
        mapping.mapped_alloy = data["mapped_alloy"]
    if "mapped_specifics" in data:
        mapping.mapped_specifics = data["mapped_specifics"]
    if "mapped_dimensions" in data:
        mapping.mapped_dimensions = data["mapped_dimensions"]
    if "mapped_unit_cost" in data:
        mapping.mapped_unit_cost = data["mapped_unit_cost"]
    if "mapped_price_unit" in data:
        mapping.mapped_price_unit = data["mapped_price_unit"]
    if "validation_notes" in data:
        mapping.validation_notes = data["validation_notes"]
    mapping.update_xero_status()
    mapping.save()

    updated = apply_mapping_to_products(mapping)
    logger.info("Validated mapping %s, updated %s related products", mapping.id, updated)
    return updated
