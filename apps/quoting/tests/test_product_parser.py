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
from django.test.utils import CaptureQueriesContext

from apps.ai.services.llm_client import LLMConfigurationError
from apps.company.models import Company
from apps.core.models import AppError
from apps.job.enums import MetalType
from apps.quoting.models import ProductParsingMapping, SupplierPriceList, SupplierProduct
from apps.quoting.services.product_parser import (
    PARSER_VERSION,
    LLMResponseError,
    ParsedProduct,
    ProductInput,
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
        assert to_optional_decimal("45.20") == Decimal("45.20")
        assert to_optional_decimal(45.2) == Decimal("45.2")
        assert to_optional_decimal(Decimal("1")) == Decimal("1")
        assert to_optional_decimal("not a price") is None
        assert to_optional_decimal(None) is None

    def test_a_boolean_is_not_a_price(self) -> None:
        """bool is an int in Python; True must not become Decimal('1')."""
        assert to_optional_decimal(True) is None


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
        assert error.data["additional_context"]["reply"] == "I could not read that."

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

        # Only the uncached one is in the prompt.
        (prompt,), _kwargs = completion.call_args
        assert ROUND_BAR in prompt
        assert FLAT_BAR not in prompt
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

    def test_a_mapping_the_model_could_not_parse_is_skipped(self) -> None:
        """One unreadable row must not abandon the rest of the batch."""
        ProductParsingMapping.objects.create(
            input_hash=product_mapping_hash(FLAT_BAR),
            input_data={"description": FLAT_BAR},
        )

        with patch(LLM_BOUNDARY, return_value="nothing parseable here"):
            assert populate_all_mappings_with_llm() == 0

        mapping = ProductParsingMapping.objects.get()
        assert mapping.mapped_item_code is None
        assert mapping.parser_version is None


class TestScraperEndOfRunFillIsBroken:
    """KNOWN DEFECT, inherited verbatim from v1 — reported, not silently fixed.

    ``BaseScraper._parse_new_products`` calls ``populate_all_mappings_with_llm``
    to fill the placeholder mappings ``create_mapping_record`` reserved during
    the run. It fills none of them and never calls the model, because a
    placeholder answers its own cache lookup:

    1. ``parse_products_batch`` looks a mapping up by ``input_hash`` alone, so
       the empty placeholder counts as a cache hit and is returned as the
       "parse result" — every field NULL, ``was_cached=True``.
    2. Even on a miss, ``_save_mapping``'s ``get_or_create`` finds the
       placeholder row and returns it WITHOUT applying ``defaults``, so the
       model's answer is thrown away.

    v1 is identical on both counts (``_get_cached_mapping`` keys on the hash;
    ``_save_mapping`` uses the same ``get_or_create``), so this is a faithful
    port of a v1 defect rather than a porting mistake. It is unreachable in v2
    today: the only caller of ``create_mapping_record`` is
    ``BaseScraper.save_products``, and no concrete scraper is ported (the
    Selenium seam).

    THE FIX NEEDS ARBITRATION, because it decides two user-visible things:
    which column means "the parser has run" (``parser_version`` is the honest
    marker; v1's ``mapped_item_code__isnull`` re-parses forever any product the
    model gave no item code), and whether filling a placeholder may overwrite a
    mapping an operator has already validated by hand. Both tests below are
    ``xfail(strict=True)``: they fail today, and they will fail LOUDLY the
    moment the fix lands, which is when they should be un-marked.
    """

    @pytest.mark.xfail(strict=True, reason="v1 defect: a placeholder answers its own cache lookup")
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

    @pytest.mark.xfail(
        strict=True, reason="v1 defect: an unparsed placeholder is back-flowed as if parsed"
    )
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
