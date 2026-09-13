"""Read-only supplier catalogue search shared by quoting tools."""

from datetime import datetime
from uuid import UUID

from django.db.models import Q
from pydantic import BaseModel

from apps.quoting.models import SupplierProduct

PAGE_SIZE = 20


class ProductPrice(BaseModel):
    """Supplier facts, including unknown prices/units and source freshness."""

    id: UUID
    supplier: str
    item_code: str
    name: str
    description: str | None
    price: float | None
    price_unit: str | None
    available_stock: int | None
    source_url: str
    recorded_at: datetime


class ProductSearchResult(BaseModel):
    """A bounded page and the total matching catalogue count."""

    products: list[ProductPrice]
    total: int
    offset: int


def search_products(query: str, offset: int = 0) -> ProductSearchResult:
    """Match every search word across product, supplier and item-code fields."""
    words = query.split()
    if not words or len(query) > 200:
        raise ValueError("Supply a search between 1 and 200 characters")
    if offset < 0 or offset > 1000:
        raise ValueError("Offset must be between 0 and 1000; refine broad searches")
    rows = SupplierProduct.objects.filter(is_discontinued=False).select_related("supplier")
    for word in words:
        rows = rows.filter(
            Q(product_name__icontains=word)
            | Q(description__icontains=word)
            | Q(item_no__icontains=word)
            | Q(supplier__name__icontains=word)
        )
    total = rows.count()
    products = [
        ProductPrice(
            id=row.id,
            supplier=row.supplier.name,
            item_code=row.item_no,
            name=row.product_name,
            description=row.description,
            price=float(row.variant_price) if row.variant_price is not None else None,
            price_unit=row.price_unit,
            available_stock=row.variant_available_stock,
            source_url=row.url,
            recorded_at=row.last_scraped,
        )
        for row in rows.order_by("supplier__name", "product_name", "id")[
            offset : offset + PAGE_SIZE
        ]
    ]
    return ProductSearchResult(products=products, total=total, offset=offset)
