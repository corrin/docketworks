"""LLM product parsing: prompting, JSON extraction, the mapping table, back-flow.

The LLM is mocked at ``LLM_BOUNDARY`` (``apps.ai``'s gateway, where the parser
binds it) and NOWHERE else, so every layer above it runs for real: the few-shot
prompt is rendered, the reply is scanned for JSON, the mapping row is written
through the real ORM against the real CHECK constraints, and the back-flow
updates real ``SupplierProduct`` rows.

Two behaviours here are the whole reason the mapping table exists, and both are
asserted end to end rather than by counting calls alone:

- the same product text is sent to the model at most once, ever;
- what the model said is persisted, and an operator's later correction of it
  survives (``apps.purchasing`` owns the correction endpoint; the back-flow it
  calls is ``apply_mapping_to_products``, tested here).

The KNOWN DEFECT in the scraper's end-of-run fill is at the bottom of this file,
under ``TestScraperEndOfRunFillIsBroken``.
"""

import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.db.models import Q
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Staff
from apps.ai.services.llm_client import LLMConfigurationError
from apps.company.models import Company
from apps.core.models import AppError
from apps.job.enums import MetalType
from apps.purchasing.services.supplier_pricing_service import validate_product_mapping
from apps.quoting.models import ProductParsingMapping, SupplierPriceList, SupplierProduct
from apps.quoting.services.product_parser import (
    PARSER_VERSION,
    LLMResponseError,
    ParsedProduct,
    ProductInput,
    _hash_matches_stored_input,
    apply_mapping_to_products,
    blank_to_none,
    build_parsing_prompt,
    create_mapping_record,
    extract_json_objects,
    input_from_mapping,
    parse_product,
    parse_products_batch,
    populate_all_mappings_with_llm,
    product_mapping_hash,
    supplier_product_mapping_hash,
    to_optional_decimal,
)
from apps.quoting.tests.conftest import LLM_BOUNDARY, llm_reply, make_price_list

pytestmark = [pytest.mark.django_db]

FLAT_BAR = "30mm x 10mm 304 HRAP Stainless Steel Flat Bar ASTM A276"
ROUND_BAR = "6061 T6 Aluminium Round Bar 25mm Diameter"

PARSED_FLAT_BAR = {
    "item_code": "FB-3010-304HRAP",
    "description": "30mm x 10mm 304 HRAP Stainless Steel Flat Bar",
    "metal_type": "stainless_steel",
    "alloy": "304",
    "specifics": "HRAP finish, ASTM A276",
    "dimensions": "30x10mm",
    "unit_cost": 45.20,
    "price_unit": "per metre",
    "confidence": 0.95,
}


@pytest.fixture
def price_list(supplier: Company) -> SupplierPriceList:
    """A price list to hang scraped products off."""
    return make_price_list(supplier)


class TestHashing:
    """The hash IS the mapping's identity: same text in, same mapping out."""

    def test_the_hash_is_taken_over_the_description_when_there_is_one(self) -> None:
        named_only = ProductInput(product_name=FLAT_BAR)
        described = ProductInput(product_name="Anything else", description=FLAT_BAR)

        assert described.hash_source == FLAT_BAR
        assert named_only.hash_source == FLAT_BAR
        assert product_mapping_hash(described.hash_source) == product_mapping_hash(
            named_only.hash_source
        )

    def test_different_text_gets_a_different_mapping(self) -> None:
        assert product_mapping_hash(FLAT_BAR) != product_mapping_hash(ROUND_BAR)

    def test_a_stored_product_hashes_the_same_way_as_its_parser_input(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        """The scraper and the parser must agree, or mappings never join up."""
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Flat bar",
            item_no="FB-1",
            variant_id="v1",
            url="https://example.test/fb-1",
            description=FLAT_BAR,
        )

        assert supplier_product_mapping_hash(product) == product_mapping_hash(FLAT_BAR)


class TestPrompt:
    """The prompt is rendered for real; these assert what the model is actually told."""

    def test_every_valid_metal_type_is_offered_to_the_model(self) -> None:
        prompt = build_parsing_prompt([ProductInput(description=FLAT_BAR)])

        for value, _label in MetalType.choices:
            assert value in prompt

    def test_each_product_is_numbered_and_carries_its_own_fields(self) -> None:
        prompt = build_parsing_prompt(
            [
                ProductInput(product_name="Flat bar", description=FLAT_BAR, item_no="FB-1"),
                ProductInput(
                    product_name="Round bar",
                    description=ROUND_BAR,
                    variant_price=Decimal("12.50"),
                    price_unit="each",
                ),
            ]
        )

        assert "Product 1:" in prompt
        assert "Product 2:" in prompt
        assert FLAT_BAR in prompt
        assert ROUND_BAR in prompt
        assert "FB-1" in prompt
        assert "12.50 each" in prompt

    def test_missing_fields_are_shown_as_not_available_not_as_blanks(self) -> None:
        """A blank line would read as 'the supplier said nothing here' ambiguously."""
        prompt = build_parsing_prompt([ProductInput(description=FLAT_BAR)])

        assert "Product Name: N/A" in prompt
        assert "Specifications: N/A" in prompt
        assert "Price: N/A N/A" in prompt

    def test_the_prompt_the_model_receives_is_the_rendered_one(
        self,
        gemini_provider: object,  # noqa: ARG002 -- the parser resolves a provider
    ) -> None:
        """Nothing between the caller and the gateway rewrites the prompt."""
        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)) as completion:
            parse_product(ProductInput(description=FLAT_BAR))

        (prompt,), kwargs = completion.call_args
        assert FLAT_BAR in prompt
        assert "TRAINING EXAMPLES:" in prompt
        assert kwargs["provider_type"] == "Gemini"


class TestExtractJsonObjects:
    """Models wrap their JSON in fences and prose; v1's scan survives that."""

    def test_a_bare_array_is_read(self) -> None:
        assert extract_json_objects('[{"item_code": "A"}]') == [{"item_code": "A"}]

    def test_a_markdown_fenced_array_is_read(self) -> None:
        reply = 'Here you go:\n```json\n[{"item_code": "A"}]\n```\nHope that helps!'

        assert extract_json_objects(reply) == [{"item_code": "A"}]

    def test_a_lone_object_becomes_a_one_row_list(self) -> None:
        assert extract_json_objects('Sure: {"item_code": "A"}') == [{"item_code": "A"}]

    def test_prose_with_no_json_raises(self) -> None:
        with pytest.raises(LLMResponseError, match="No JSON found"):
            extract_json_objects("I could not read that file, sorry.")

    def test_an_unterminated_array_raises(self) -> None:
        with pytest.raises(LLMResponseError, match="Unterminated JSON"):
            extract_json_objects('[{"item_code": "A"}')

    def test_an_array_of_non_objects_raises(self) -> None:
        with pytest.raises(LLMResponseError, match="non-object element"):
            extract_json_objects('["FB-3010", "RB-25"]')

    def test_malformed_json_raises_the_decoder_error(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            extract_json_objects('[{"item_code": }]')


class TestScalarNormalisation:
    """Both helpers exist because the model does not respect the schema it is given."""

    def test_a_blank_answer_becomes_null_so_the_check_constraint_holds(self) -> None:
        assert blank_to_none("  ") is None
        assert blank_to_none("") is None
        assert blank_to_none(None) is None
        assert blank_to_none(42) is None
        assert blank_to_none("  304 ") == "304"

    def test_numbers_are_coerced_and_non_numbers_are_dropped(self) -> None:
        assert to_optional_decimal("45.20", max_digits=10, decimal_places=2) == Decimal("45.20")
        assert to_optional_decimal(45.2, max_digits=10, decimal_places=2) == Decimal("45.2")
        assert to_optional_decimal(Decimal("1"), max_digits=10, decimal_places=2) == Decimal("1")
        assert to_optional_decimal("not a price", max_digits=10, decimal_places=2) is None
        assert to_optional_decimal(None, max_digits=10, decimal_places=2) is None

    def test_a_boolean_is_not_a_price(self) -> None:
        """bool is an int in Python; True must not become Decimal('1')."""
        assert to_optional_decimal(True, max_digits=10, decimal_places=2) is None

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "nan", float("nan")])
    def test_a_non_finite_number_is_not_a_price(self, value: object) -> None:
        """Decimal parses these and numeric(10,2) stores them; comparisons then rot."""
        assert to_optional_decimal(value, max_digits=10, decimal_places=2) is None

    def test_a_non_finite_decimal_is_rejected_too(self) -> None:
        """The Decimal fast path must not be a way in for NaN."""
        assert to_optional_decimal(Decimal("NaN"), max_digits=10, decimal_places=2) is None

    @pytest.mark.parametrize("value", [95, "95", Decimal("10"), -10, "1e6"])
    def test_a_number_too_big_for_its_column_is_not_a_value(self, value: object) -> None:
        """numeric(3,2) holds |x| < 10: a model answering percent must become None.

        Anything bigger raises DataError at save time — and one poison row used
        to kill its whole batch plus every remaining batch of the run.
        """
        assert to_optional_decimal(value, max_digits=3, decimal_places=2) is None

    def test_the_column_bound_is_exclusive_at_the_precision_limit(self) -> None:
        assert to_optional_decimal("9.99", max_digits=3, decimal_places=2) == Decimal("9.99")
        assert to_optional_decimal("99999999.99", max_digits=10, decimal_places=2) == Decimal(
            "99999999.99"
        )
        assert to_optional_decimal("100000000", max_digits=10, decimal_places=2) is None

    def test_a_percent_confidence_is_dropped_but_the_mapping_still_saves(self) -> None:
        """The v1 "0 of 7,614 enriched" symptom: overflow must not reach the DB."""
        reply = dict(PARSED_FLAT_BAR, confidence=95)

        with patch(LLM_BOUNDARY, return_value=llm_reply(reply)):
            parsed, _ = parse_product(ProductInput(description=FLAT_BAR))

        assert parsed is not None
        mapping = ProductParsingMapping.objects.get()
        assert mapping.parser_confidence is None
        assert mapping.mapped_item_code == "FB-3010-304HRAP"


class TestParseProduct:
    def test_a_new_product_is_parsed_and_the_result_persisted(self) -> None:
        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)) as completion:
            parsed, was_cached = parse_product(ProductInput(description=FLAT_BAR))

        assert completion.call_count == 1
        assert was_cached is False
        assert parsed == ParsedProduct(
            item_code="FB-3010-304HRAP",
            description="30mm x 10mm 304 HRAP Stainless Steel Flat Bar",
            metal_type="stainless_steel",
            alloy="304",
            specifics="HRAP finish, ASTM A276",
            dimensions="30x10mm",
            unit_cost=Decimal("45.2"),
            price_unit="per metre",
            confidence=Decimal("0.95"),
            parser_version=PARSER_VERSION,
        )

        mapping = ProductParsingMapping.objects.get()
        assert mapping.input_hash == product_mapping_hash(FLAT_BAR)
        assert mapping.mapped_item_code == "FB-3010-304HRAP"
        assert mapping.parser_version == PARSER_VERSION
        assert mapping.llm_response == [PARSED_FLAT_BAR]

    def test_input_data_is_stored_in_the_one_canonical_shape(self) -> None:
        """v1 wrote two shapes and read both with fallbacks; v2 writes one dict."""
        product = ProductInput(
            product_name="Flat bar",
            description=FLAT_BAR,
            specifications="ASTM A276",
            item_no="FB-1",
            variant_id="v1",
            variant_width="30",
            variant_length="6000",
            variant_price=Decimal("45.20"),
            price_unit="per metre",
        )
        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)):
            parse_product(product)

        assert ProductParsingMapping.objects.get().input_data == {
            "product_name": "Flat bar",
            "description": FLAT_BAR,
            "specifications": "ASTM A276",
            "item_no": "FB-1",
            "variant_id": "v1",
            "variant_width": "30",
            "variant_length": "6000",
            "variant_price": "45.20",
            "price_unit": "per metre",
        }

    def test_the_same_text_is_never_sent_to_the_model_twice(self) -> None:
        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)) as completion:
            first, first_cached = parse_product(ProductInput(description=FLAT_BAR))
            second, second_cached = parse_product(ProductInput(description=FLAT_BAR))

        assert completion.call_count == 1
        assert first_cached is False
        assert second_cached is True
        assert first == second
        assert ProductParsingMapping.objects.count() == 1

    def test_a_blank_string_from_the_model_is_stored_as_null(self) -> None:
        """Every mapped_* column has a *_not_blank CHECK: "" would be an IntegrityError."""
        reply = llm_reply({"item_code": "FB-1", "alloy": "   ", "specifics": ""})
        with patch(LLM_BOUNDARY, return_value=reply):
            parsed, _cached = parse_product(ProductInput(description=FLAT_BAR))

        assert parsed is not None
        assert parsed.alloy is None
        assert parsed.specifics is None
        mapping = ProductParsingMapping.objects.get()
        assert mapping.mapped_alloy is None
        assert mapping.mapped_specifics is None

    def test_an_unusable_reply_yields_no_result_and_persists_the_failure(self) -> None:
        with patch(LLM_BOUNDARY, return_value="I could not read that."):
            parsed, was_cached = parse_product(ProductInput(description=FLAT_BAR))

        assert parsed is None
        assert was_cached is False
        assert not ProductParsingMapping.objects.exists()

        error = AppError.objects.get()
        assert "No JSON found" in error.message
        assert error.data is not None
        # ADR 0038: the persisted row carries what the model actually said.
        assert error.data["reply"] == "I could not read that."
        assert error.data["products"] == 1

    def test_an_unconfigured_shop_raises_instead_of_looking_like_a_bad_answer(self) -> None:
        """ADR 0015: a missing provider is a configuration fault, not an empty result."""
        assert not ProductParsingMapping.objects.exists()

        with pytest.raises(LLMConfigurationError, match="No AI provider of type Gemini"):
            parse_product(ProductInput(description=FLAT_BAR))


class TestParseProductsBatch:
    def test_nothing_in_nothing_out_and_no_model_call(self) -> None:
        with patch(LLM_BOUNDARY) as completion:
            assert parse_products_batch([]) == []

        completion.assert_not_called()

    def test_one_round_trip_covers_every_uncached_product_in_order(self) -> None:
        reply = llm_reply({"item_code": "FB-1"}, {"item_code": "RB-1"})
        with patch(LLM_BOUNDARY, return_value=reply) as completion:
            results = parse_products_batch(
                [ProductInput(description=FLAT_BAR), ProductInput(description=ROUND_BAR)]
            )

        assert completion.call_count == 1
        assert [result[0].item_code for result in results if result[0] is not None] == [
            "FB-1",
            "RB-1",
        ]
        assert [cached for _parsed, cached in results] == [False, False]

    def test_cached_products_are_skipped_and_the_results_stay_aligned(self) -> None:
        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "FB-1"})):
            parse_product(ProductInput(description=FLAT_BAR))

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "RB-1"})) as completion:
            results = parse_products_batch(
                [ProductInput(description=FLAT_BAR), ProductInput(description=ROUND_BAR)]
            )

        # Only the uncached one is in the prompt's input section (FLAT_BAR also
        # appears verbatim in the few-shot training examples, which is why the
        # assertion is scoped to the part after the input header).
        (prompt,), _kwargs = completion.call_args
        _examples, _, inputs = prompt.partition("INPUT DATA TO PARSE:")
        assert ROUND_BAR in inputs
        assert FLAT_BAR not in inputs
        assert [cached for _parsed, cached in results] == [True, False]
        assert [result[0].item_code for result in results if result[0] is not None] == [
            "FB-1",
            "RB-1",
        ]

    def test_a_short_reply_falls_back_to_one_call_per_product(self) -> None:
        """Otherwise row 2's answer silently lands on row 1 (v1 kept this guard)."""
        replies = [
            llm_reply({"item_code": "ONLY-ONE"}),  # batch call: one row for two inputs
            llm_reply({"item_code": "FB-1"}),
            llm_reply({"item_code": "RB-1"}),
        ]
        with patch(LLM_BOUNDARY, side_effect=replies) as completion:
            results = parse_products_batch(
                [ProductInput(description=FLAT_BAR), ProductInput(description=ROUND_BAR)]
            )

        assert completion.call_count == 3
        assert [result[0].item_code for result in results if result[0] is not None] == [
            "FB-1",
            "RB-1",
        ]

    def test_an_unusable_batch_reply_still_yields_a_result_per_input(self) -> None:
        with patch(LLM_BOUNDARY, return_value="nope") as completion:
            results = parse_products_batch(
                [ProductInput(description=FLAT_BAR), ProductInput(description=ROUND_BAR)]
            )

        # One batch attempt, then one retry per product; all unusable.
        assert completion.call_count == 3
        assert results == [(None, False), (None, False)]


class TestCreateMappingRecord:
    def test_a_scraped_product_is_stamped_and_its_mapping_reserved(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Flat bar",
            item_no="FB-1",
            variant_id="v1",
            url="https://example.test/fb-1",
            description=FLAT_BAR,
        )

        mapping = create_mapping_record(product)
        product.refresh_from_db()

        assert product.mapping_hash == product_mapping_hash(FLAT_BAR)
        assert mapping.input_hash == product.mapping_hash
        # Reserved, not parsed: the LLM fills it in later, in bulk.
        assert mapping.mapped_item_code is None
        assert mapping.parser_version is None
        assert mapping.input_data["description"] == FLAT_BAR

    def test_two_variants_of_the_same_text_share_one_mapping(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        """One LLM call per distinct description, however many variants carry it."""
        products = [
            SupplierProduct.objects.create(
                supplier=supplier,
                price_list=price_list,
                product_name="Flat bar",
                item_no="FB-1",
                variant_id=variant,
                url=f"https://example.test/fb-1-{variant}",
                description=FLAT_BAR,
            )
            for variant in ("v1", "v2")
        ]

        mappings = [create_mapping_record(product) for product in products]

        assert mappings[0].pk == mappings[1].pk
        assert ProductParsingMapping.objects.count() == 1

    def test_a_product_with_no_description_is_keyed_by_its_name(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name=FLAT_BAR,
            item_no="FB-1",
            variant_id="v1",
            url="https://example.test/fb-1",
            description=None,
        )

        mapping = create_mapping_record(product)

        assert mapping.input_hash == product_mapping_hash(FLAT_BAR)


class TestInputFromMapping:
    def test_a_stored_mapping_round_trips_back_to_its_parser_input(self) -> None:
        original = ProductInput(
            product_name="Flat bar",
            description=FLAT_BAR,
            specifications="ASTM A276",
            item_no="FB-1",
            variant_id="v1",
            variant_width="30",
            variant_length="6000",
            variant_price=Decimal("45.20"),
            price_unit="per metre",
        )
        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)):
            parse_product(original)

        assert input_from_mapping(ProductParsingMapping.objects.get()) == original

    def test_a_v1_json_string_input_data_raises_rather_than_falling_back(self) -> None:
        """ADR 0015: the v1 shape is a data problem to migrate, not a read-side branch."""
        mapping = ProductParsingMapping.objects.create(
            input_hash=product_mapping_hash(FLAT_BAR),
            input_data=json.dumps({"input_description": FLAT_BAR}),
        )

        with pytest.raises(TypeError, match="input_data of type str"):
            input_from_mapping(mapping)


class TestApplyMappingToProducts:
    """THE one mapping → SupplierProduct.parsed_* implementation (ADR 0039)."""

    def _product(
        self, supplier: Company, price_list: SupplierPriceList, *, variant: str, description: str
    ) -> SupplierProduct:
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Flat bar",
            item_no="FB-1",
            variant_id=variant,
            url=f"https://example.test/fb-1-{variant}",
            description=description,
        )
        create_mapping_record(product)
        product.refresh_from_db()
        return product

    def test_every_product_sharing_the_hash_gets_the_mapped_values(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        first = self._product(supplier, price_list, variant="v1", description=FLAT_BAR)
        second = self._product(supplier, price_list, variant="v2", description=FLAT_BAR)
        other = self._product(supplier, price_list, variant="v3", description=ROUND_BAR)

        mapping = ProductParsingMapping.objects.get(input_hash=first.mapping_hash)
        mapping.mapped_item_code = "FB-3010-304HRAP"
        mapping.mapped_metal_type = "stainless_steel"
        mapping.mapped_alloy = "304"
        mapping.mapped_unit_cost = Decimal("45.20")
        mapping.parser_version = PARSER_VERSION
        mapping.parser_confidence = Decimal("0.95")
        mapping.save()

        assert apply_mapping_to_products(mapping) == 2

        for product in (first, second):
            product.refresh_from_db()
            assert product.parsed_item_code == "FB-3010-304HRAP"
            assert product.parsed_metal_type == "stainless_steel"
            assert product.parsed_alloy == "304"
            assert product.parsed_unit_cost == Decimal("45.20")
            assert product.parser_version == PARSER_VERSION
            assert product.parser_confidence == Decimal("0.95")
            assert product.parsed_at is not None

        other.refresh_from_db()
        assert other.parsed_item_code is None
        assert other.parsed_at is None

    def test_a_mapping_no_product_carries_updates_nothing(self) -> None:
        mapping = ProductParsingMapping.objects.create(
            input_hash=product_mapping_hash(FLAT_BAR),
            input_data={"description": FLAT_BAR},
            mapped_item_code="FB-1",
        )

        assert apply_mapping_to_products(mapping) == 0

    def test_the_back_flow_is_one_statement_not_a_row_loop(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        """A scrape back-flows thousands of variants; per-row saves would not do."""
        for variant in ("v1", "v2", "v3"):
            self._product(supplier, price_list, variant=variant, description=FLAT_BAR)
        mapping = ProductParsingMapping.objects.get(input_hash=product_mapping_hash(FLAT_BAR))
        mapping.mapped_item_code = "FB-3010-304HRAP"
        mapping.save()

        with CaptureQueriesContext(connection) as queries:
            assert apply_mapping_to_products(mapping) == 3

        assert len(queries) == 1


class TestPopulateAllMappingsWithLlm:
    def test_no_placeholders_means_no_work_and_no_model_call(self) -> None:
        with patch(LLM_BOUNDARY) as completion:
            assert populate_all_mappings_with_llm() == 0

        completion.assert_not_called()


class TestScraperEndOfRunFill:
    """The scrape's end-of-run fill: it calls the model, and the operator wins.

    ``BaseScraper._parse_new_products`` calls ``populate_all_mappings_with_llm``
    to fill the placeholders ``create_mapping_record`` reserved during the run.
    In v1 — and in v2 until 2026-08-03 — it filled none of them and never called
    the model, for two independent reasons, both ported verbatim from v1:

    1. ``parse_products_batch`` looked a mapping up by ``input_hash`` alone, so
       the empty placeholder answered its own cache lookup and came back as the
       "parse result" with every field NULL.
    2. Even on a miss, ``_save_mapping``'s ``get_or_create`` found the
       placeholder and returned it WITHOUT applying ``defaults``, discarding the
       model's answer.

    Confirmed live in the 2026-08-01 production restore: 559 of 1,203 mappings
    never parsed (every scraper-created one), and 0 of 7,614 supplier products
    carrying any parsed data.

    Both causes are fixed via ``AUTHORITATIVE_MAPPING``, which is the single
    predicate behind the cache lookup and the fill's work list. The two user
    decisions it encodes (2026-08-03) are asserted below: ``parser_version`` at
    the current version is the "parser has run" marker, and a hand-validated
    mapping is never re-parsed or overwritten.
    """

    def test_the_end_of_run_fill_actually_calls_the_model(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Flat bar",
            item_no="FB-1",
            variant_id="v1",
            url="https://example.test/fb-1",
            description=FLAT_BAR,
        )
        create_mapping_record(product)

        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)) as completion:
            populated = populate_all_mappings_with_llm()

        assert completion.call_count == 1
        assert populated == 1
        mapping = ProductParsingMapping.objects.get()
        assert mapping.mapped_item_code == "FB-3010-304HRAP"
        assert mapping.parser_version == PARSER_VERSION
        product.refresh_from_db()
        assert product.parsed_item_code == "FB-3010-304HRAP"

    def test_an_unfilled_placeholder_does_not_mark_its_products_parsed(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        """The worst symptom: the review screen shows NULL data as a finished parse."""
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Flat bar",
            item_no="FB-1",
            variant_id="v1",
            url="https://example.test/fb-1",
            description=FLAT_BAR,
        )
        create_mapping_record(product)

        with patch(LLM_BOUNDARY, return_value="nothing parseable here"):
            populate_all_mappings_with_llm()

        product.refresh_from_db()
        assert product.parsed_at is None

    def test_a_product_the_model_cannot_classify_is_never_re_parsed(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        """DECISION A: parser_version marks the attempt, so one row costs one call.

        v1 keyed the work list on ``mapped_item_code__isnull``, so a product the
        model could not name an item code for came back round every single week,
        forever, burning a call each time.
        """
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Flat bar",
            item_no="FB-1",
            variant_id="v1",
            url="https://example.test/fb-1",
            description=FLAT_BAR,
        )
        create_mapping_record(product)

        # The model answers, but cannot classify it: no item code.
        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": None})) as first:
            assert populate_all_mappings_with_llm() == 1
        assert first.call_count == 1

        mapping = ProductParsingMapping.objects.get()
        assert mapping.mapped_item_code is None
        assert mapping.parser_version == PARSER_VERSION

        # Next week's scrape must not ask again.
        with patch(LLM_BOUNDARY) as second:
            assert populate_all_mappings_with_llm() == 0
        second.assert_not_called()

    def test_bumping_the_parser_version_re_parses_everything(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        """DECISION A's re-run lever: a prompt change is deployed as a version bump."""
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Flat bar",
            item_no="FB-1",
            variant_id="v1",
            url="https://example.test/fb-1",
            description=FLAT_BAR,
        )
        create_mapping_record(product)
        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)):
            assert populate_all_mappings_with_llm() == 1

        with (
            patch("apps.quoting.services.product_parser.PARSER_VERSION", "2.0.0"),
            patch(
                "apps.quoting.services.product_parser.AUTHORITATIVE_MAPPING",
                Q(parser_version="2.0.0") | Q(is_validated=True),
            ),
            patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "FB-V2"})) as completion,
        ):
            assert populate_all_mappings_with_llm() == 1

        assert completion.call_count == 1
        mapping = ProductParsingMapping.objects.get()
        assert mapping.mapped_item_code == "FB-V2"
        assert mapping.parser_version == "2.0.0"

    def test_a_hand_validated_mapping_is_never_re_parsed_or_overwritten(
        self, supplier: Company, price_list: SupplierPriceList, office_staff: Staff
    ) -> None:
        """DECISION B: the operator wins, or the review screen is worthless."""
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Flat bar",
            item_no="FB-1",
            variant_id="v1",
            url="https://example.test/fb-1",
            description=FLAT_BAR,
        )
        create_mapping_record(product)
        mapping = ProductParsingMapping.objects.get()

        # An operator corrects it on the review screen before the fill runs.
        # NB: mapped_item_code is deliberately NOT used as the marker here —
        # validate_product_mapping runs update_xero_status(), which clears an item
        # code that does not exist in Stock. That rule is correct and ported; this
        # test is about Decision B, not about it.
        validate_product_mapping(
            mapping,
            {
                "mapped_description": "OPERATOR DESCRIPTION",
                "validation_notes": "Checked against the shelf",
            },
            office_staff,
        )

        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)) as completion:
            assert populate_all_mappings_with_llm() == 0

        completion.assert_not_called()
        mapping.refresh_from_db()
        assert mapping.mapped_description == "OPERATOR DESCRIPTION"
        assert mapping.validation_notes == "Checked against the shelf"
        assert mapping.is_validated is True

    def test_an_unvalidated_placeholder_beside_it_is_still_filled(
        self, supplier: Company, price_list: SupplierPriceList, office_staff: Staff
    ) -> None:
        """DECISION B skips validated rows only — it must not stall the whole run."""
        for variant, description in (("v1", FLAT_BAR), ("v2", ROUND_BAR)):
            create_mapping_record(
                SupplierProduct.objects.create(
                    supplier=supplier,
                    price_list=price_list,
                    product_name="Bar",
                    item_no=f"BAR-{variant}",
                    variant_id=variant,
                    url=f"https://example.test/bar-{variant}",
                    description=description,
                )
            )
        validated = ProductParsingMapping.objects.get(input_hash=product_mapping_hash(FLAT_BAR))
        validate_product_mapping(
            validated, {"mapped_description": "OPERATOR DESCRIPTION"}, office_staff
        )

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "RB-1"})) as completion:
            assert populate_all_mappings_with_llm() == 1

        assert completion.call_count == 1
        (prompt,), _kwargs = completion.call_args
        _examples, _, inputs = prompt.partition("INPUT DATA TO PARSE:")
        assert ROUND_BAR in inputs
        assert FLAT_BAR not in inputs

        validated.refresh_from_db()
        assert validated.mapped_description == "OPERATOR DESCRIPTION"
        filled = ProductParsingMapping.objects.get(input_hash=product_mapping_hash(ROUND_BAR))
        assert filled.mapped_item_code == "RB-1"

    def test_a_concurrent_validation_is_not_reverted_by_the_fill(
        self, supplier: Company, price_list: SupplierPriceList, office_staff: Staff
    ) -> None:
        """The fill reads its work list first; an operator may validate mid-run."""
        create_mapping_record(
            SupplierProduct.objects.create(
                supplier=supplier,
                price_list=price_list,
                product_name="Flat bar",
                item_no="FB-1",
                variant_id="v1",
                url="https://example.test/fb-1",
                description=FLAT_BAR,
            )
        )
        mapping = ProductParsingMapping.objects.get()

        def validate_then_answer(_prompt: str, **_kwargs: object) -> str:
            # The operator validates while the LLM round-trip is in flight.
            validate_product_mapping(
                ProductParsingMapping.objects.get(pk=mapping.pk),
                {"mapped_description": "OPERATOR DESCRIPTION", "validation_notes": "Mid-run"},
                office_staff,
            )
            return llm_reply(PARSED_FLAT_BAR)

        with patch(LLM_BOUNDARY, side_effect=validate_then_answer):
            populate_all_mappings_with_llm()

        mapping.refresh_from_db()
        assert mapping.is_validated is True
        assert mapping.validation_notes == "Mid-run"
        assert mapping.mapped_description == "OPERATOR DESCRIPTION"


class TestAMappingThatLostItsText:
    """``_hash_matches_stored_input``: the guard between the cache and a "" parse.

    A row whose ``input_data`` lost the text it was keyed by would otherwise be
    parsed as the empty string, filed under ``sha256("")``, and its products
    back-flowed with someone else's values.
    """

    def _product_with_placeholder(
        self, supplier: Company, price_list: SupplierPriceList, *, description: str, item_no: str
    ) -> tuple[SupplierProduct, ProductParsingMapping]:
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name=description,
            item_no=item_no,
            variant_id="v1",
            url=f"https://example.test/{item_no}",
            description=description,
        )
        create_mapping_record(product)
        return product, ProductParsingMapping.objects.get(input_hash=product.mapping_hash)

    def _corrupt(self, mapping: ProductParsingMapping) -> None:
        """Blank the text fields the hash was taken over, as v1 data rot did."""
        stripped = dict(mapping.input_data)
        stripped["description"] = ""
        stripped["product_name"] = ""
        ProductParsingMapping.objects.filter(pk=mapping.pk).update(input_data=stripped)
        mapping.refresh_from_db()

    def test_an_intact_mapping_hashes_to_its_own_key(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        _, mapping = self._product_with_placeholder(
            supplier, price_list, description=FLAT_BAR, item_no="FB-1"
        )

        assert _hash_matches_stored_input(mapping) is True
        assert AppError.objects.count() == 0

    def test_a_mapping_that_no_longer_hashes_to_its_key_is_refused_and_persisted(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        _, mapping = self._product_with_placeholder(
            supplier, price_list, description=FLAT_BAR, item_no="FB-1"
        )
        self._corrupt(mapping)

        assert _hash_matches_stored_input(mapping) is False
        error = AppError.objects.get()
        assert error.data is not None
        assert error.data["input_hash"] == mapping.input_hash

    def test_the_fill_skips_the_corrupt_row_and_still_parses_the_rest(
        self, supplier: Company, price_list: SupplierPriceList
    ) -> None:
        corrupt_product, corrupt_mapping = self._product_with_placeholder(
            supplier, price_list, description=ROUND_BAR, item_no="RB-1"
        )
        self._corrupt(corrupt_mapping)
        good_product, _ = self._product_with_placeholder(
            supplier, price_list, description=FLAT_BAR, item_no="FB-1"
        )

        with patch(LLM_BOUNDARY, return_value=llm_reply(PARSED_FLAT_BAR)):
            populated = populate_all_mappings_with_llm()

        assert populated == 1
        good_product.refresh_from_db()
        assert good_product.parsed_item_code == "FB-3010-304HRAP"
        # The corrupt row was not parsed as "": no stray sha256("") mapping,
        # no back-flow, and the placeholder is still a placeholder.
        assert not ProductParsingMapping.objects.filter(
            input_hash=product_mapping_hash("")
        ).exists()
        corrupt_mapping.refresh_from_db()
        assert corrupt_mapping.parser_version is None
        corrupt_product.refresh_from_db()
        assert corrupt_product.parsed_at is None
