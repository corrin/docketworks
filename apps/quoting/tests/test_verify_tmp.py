"""Verify reviewer MAJOR findings 1-4. Throwaway."""
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.accounts.models import Staff
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job
from apps.purchasing.models import Stock
from apps.purchasing.tasks import stock_metadata_parse_eligible
from apps.quoting.models import ProductParsingMapping
from apps.quoting.services.product_parser import (
    ProductInput, parse_product, product_mapping_hash, input_from_mapping,
    populate_all_mappings_with_llm, to_optional_decimal,
)
from apps.quoting.services.stock_parser import auto_parse_stock_item
from apps.quoting.tests.conftest import LLM_BOUNDARY

pytestmark = [pytest.mark.django_db]
TEXT = "2.0X1200X3000 5005H32 AL SHTPE"


def _job():
    Stock._stock_holding_job = None
    staff = Staff.objects.create_user(
        email="v@example.com", password="s3cret-Pass!", first_name="V", last_name="W",
        is_office_staff=True, base_wage_rate=Decimal("40.00"))
    return make_job(make_company("Verify Co"), staff, name="Verify Job")


def test_major1_empty_object_reply_becomes_a_permanent_poison_mapping():
    with patch(LLM_BOUNDARY, return_value="[{}]") as c:
        parsed, cached = parse_product(ProductInput(description=TEXT))
    assert c.call_count == 1
    m = ProductParsingMapping.objects.get()
    print(f"\nMAJOR1: parser_version={m.parser_version!r} item_code={m.mapped_item_code!r} "
          f"parsed={parsed} cached={cached}")
    # Is it now served as a cache hit forever?
    with patch(LLM_BOUNDARY, return_value="[{}]") as c2:
        p2, cached2 = parse_product(ProductInput(description=TEXT))
    print(f"MAJOR1: second call -> llm_calls={c2.call_count} cached={cached2}")
    # Is it indistinguishable from a placeholder for populate?
    n = ProductParsingMapping.objects.filter(mapped_item_code__isnull=True).count()
    print(f"MAJOR1: rows populate() would re-select forever = {n}")


def test_major2_placeholder_burns_the_stock_rows_one_attempt():
    job = _job()
    # A placeholder exists for this text (scraper reserved it).
    ProductParsingMapping.objects.create(input_hash=product_mapping_hash(TEXT), input_data={"description": TEXT})
    stock = Stock.objects.create(job=job, description=TEXT, quantity=Decimal("1"),
                                 unit_cost=Decimal("10"), source="manual")
    assert stock_metadata_parse_eligible(stock) is True
    with patch(LLM_BOUNDARY) as c:
        auto_parse_stock_item(stock)
    stock.refresh_from_db()
    print(f"\nMAJOR2: llm_calls={c.call_count} attempted_at_set={stock.parser_attempted_at is not None} "
          f"metal_type={stock.metal_type!r} still_eligible={stock_metadata_parse_eligible(stock)}")


def test_major3_update_mapping_reverts_operator_validation():
    job = _job()
    h = product_mapping_hash(TEXT)
    ProductParsingMapping.objects.create(input_hash=h, input_data={"description": TEXT})
    stale = list(ProductParsingMapping.objects.filter(mapped_item_code__isnull=True))[0]
    # Operator validates concurrently, after the snapshot was taken.
    ProductParsingMapping.objects.filter(input_hash=h).update(
        is_validated=True, validation_notes="Operator checked this")
    from apps.quoting.services.product_parser import _update_mapping, ParsedProduct
    _update_mapping(stale, ParsedProduct("IC", "D", None, None, None, None, None, None, None, "1.1.0"))
    fresh = ProductParsingMapping.objects.get(input_hash=h)
    print(f"\nMAJOR3: after _update_mapping -> is_validated={fresh.is_validated} "
          f"notes={fresh.validation_notes!r}")


def test_major4_missing_description_key_hashes_to_empty_string():
    m = ProductParsingMapping.objects.create(input_hash="d" * 64, input_data={"specifications": "x"})
    rebuilt = input_from_mapping(m)
    print(f"\nMAJOR4: rebuilt.hash_source={rebuilt.hash_source!r} "
          f"rebuilt_hash={product_mapping_hash(rebuilt.hash_source)[:12]} "
          f"stored_hash={m.input_hash[:12]} MATCH={product_mapping_hash(rebuilt.hash_source)==m.input_hash}")


def test_minor5_nan_and_inf():
    print(f"\nMINOR5: nan->{to_optional_decimal('nan')!r} inf->{to_optional_decimal('inf')!r}")
