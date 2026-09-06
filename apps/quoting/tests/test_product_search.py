"""Catalogue answers distinguish unknown prices, withdrawn products and bounded results."""

from decimal import Decimal

import pytest

from apps.company.models import Company
from apps.quoting.services.product_search import PAGE_SIZE, search_products
from apps.quoting.tests.conftest import make_price_list, make_supplier_product

pytestmark = pytest.mark.django_db


def test_search_keeps_unknown_prices_and_excludes_discontinued_products(supplier: Company) -> None:
    price_list = make_price_list(supplier)
    known = make_supplier_product(
        supplier, price_list, variant_price=Decimal("73.29"), price_unit="per metre"
    )
    unknown = make_supplier_product(supplier, price_list, variant_id="unknown")
    make_supplier_product(supplier, price_list, variant_id="withdrawn", is_discontinued=True)
    result = search_products("SHS 50")
    assert result.total == 2
    by_id = {item.id: item for item in result.products}
    assert by_id[known.id].price == 73.29
    assert by_id[known.id].price_unit == "per metre"
    assert by_id[known.id].source_url == known.url
    assert by_id[known.id].recorded_at == known.last_scraped
    assert by_id[unknown.id].price is None and by_id[unknown.id].price_unit is None
    assert search_products("SHS copper").total == 0


def test_catalogue_results_are_bounded_and_page_without_losing_matches(supplier: Company) -> None:
    price_list = make_price_list(supplier)
    for index in range(PAGE_SIZE + 3):
        make_supplier_product(supplier, price_list, variant_id=str(index))
    first = search_products("SHS")
    second = search_products("SHS", PAGE_SIZE)
    assert first.total == second.total == PAGE_SIZE + 3
    assert len(first.products) == PAGE_SIZE and len(second.products) == 3
    assert len({item.id for item in first.products + second.products}) == PAGE_SIZE + 3


@pytest.mark.parametrize(("query", "offset"), [("", 0), ("SHS", -1), ("SHS", 1001)])
def test_invalid_searches_are_refused(query: str, offset: int) -> None:
    with pytest.raises(ValueError):
        search_products(query, offset)
