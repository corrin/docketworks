"""Stock metadata parsing: the acceptance rules, at the edges.

The end-to-end behaviour of this module — what a run writes, which timestamps it
stamps, and how a bad answer differs from an outage — is asserted in
``apps/purchasing/tests/test_stock_metadata_tasks.py``, beside the tasks that
call it, because that file is the seam closure. This one does NOT repeat any of
it (ADR 0039). It covers the parts that file leaves at one example each: the
three acceptance rules' boundaries, and what a stock row actually looks like
when it reaches the shared product parser.

``normalise_alloy`` takes a ``Stock`` but only reads three of its text columns,
so those cases use an unsaved instance — the rule is about text, not storage.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.accounts.models import Staff
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.purchasing.models import Stock
from apps.purchasing.tests.conftest import make_stock
from apps.quoting.services.stock_parser import (
    MAX_SPECIFICS_LENGTH,
    auto_parse_stock_item,
    normalise_alloy,
    normalise_metal_type,
    normalise_specifics,
)
from apps.quoting.tests.conftest import LLM_BOUNDARY, llm_reply

pytestmark = [pytest.mark.django_db]

ALUMINIUM_SHEET = "2.0X1200X3000 5005H32 AL SHTPE"


@pytest.fixture(autouse=True)
def _reset_stock_holding_cache() -> None:
    """Stock caches the stock-holding job on the class; tests get fresh rows."""
    Stock._stock_holding_job = None


@pytest.fixture
def job(office_staff: Staff) -> Job:
    """A job to hang stock rows off."""
    return make_job(make_company("Stock Parser Test Co"), office_staff, name="Stock Parser Job")


class TestNormaliseMetalType:
    """Only a real MetalType value may reach inventory; the model invents others."""

    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            ("aluminium", "aluminium"),
            ("aluminum", "aluminium"),  # American spelling
            ("ALUMINUM", "aluminium"),
            ("  aluminum  ", "aluminium"),
            ("stainless_steel", "stainless_steel"),  # already a MetalType value
            ("stainless steel", "stainless_steel"),  # spaced
            ("stainless-steel", "stainless_steel"),  # hyphenated
            ("mild steel", "mild_steel"),
            ("galvanised", "galvanized"),  # NZ spelling in, US value out
            ("galvanized", "galvanized"),
        ],
    )
    def test_the_spellings_the_model_actually_emits_are_mapped(
        self, answer: str, expected: str
    ) -> None:
        assert normalise_metal_type(answer) == expected

    @pytest.mark.parametrize("answer", ["plastic", "nylon", "unknown", "", "   ", None])
    def test_anything_that_is_not_a_metal_type_is_dropped(self, answer: str | None) -> None:
        assert normalise_metal_type(answer) is None


class TestNormaliseAlloy:
    """An alloy must appear in the row's own text — the model invents grades."""

    def _stock(self, **fields: str) -> Stock:
        return Stock(**fields)

    def test_an_alloy_named_in_the_description_is_accepted(self) -> None:
        stock = self._stock(description=ALUMINIUM_SHEET)

        assert normalise_alloy("5005", stock) == "5005"

    def test_an_alloy_named_only_in_the_item_code_is_accepted(self) -> None:
        stock = self._stock(description="Aluminium sheet", item_code="AL-5005-H32")

        assert normalise_alloy("5005", stock) == "5005"

    def test_an_alloy_named_only_in_the_specifics_is_accepted(self) -> None:
        stock = self._stock(description="Aluminium sheet", specifics="Grade 5005 H32 temper")

        assert normalise_alloy("5005", stock) == "5005"

    def test_the_match_ignores_case_and_separators(self) -> None:
        """'304' must match '304L'? No — but '6061-T6' must match '6061 T6'."""
        stock = self._stock(description="6061 T6 Aluminium Round Bar")

        assert normalise_alloy("6061-t6", stock) == "6061-T6"

    def test_an_alloy_the_row_never_mentions_is_rejected(self) -> None:
        stock = self._stock(description="2.0X1200X3000 AL SHTPE")

        assert normalise_alloy("5005", stock) is None

    def test_the_accepted_alloy_is_upper_cased(self) -> None:
        stock = self._stock(description="316l stainless plate")

        assert normalise_alloy("  316l  ", stock) == "316L"

    @pytest.mark.parametrize("answer", ["", "   ", None])
    def test_no_answer_is_no_alloy(self, answer: str | None) -> None:
        assert normalise_alloy(answer, self._stock(description=ALUMINIUM_SHEET)) is None


class TestNormaliseSpecifics:
    """Specifics are free text, so they only stick where the row has material context."""

    def test_accepted_with_material_context(self) -> None:
        assert normalise_specifics("H32 temper", has_material_context=True) == "H32 temper"

    def test_rejected_without_material_context(self) -> None:
        assert normalise_specifics("H32 temper", has_material_context=False) is None

    @pytest.mark.parametrize("boilerplate", ["Service item", "service item", "TESTING STOCK"])
    def test_generic_boilerplate_is_rejected_whatever_its_case(self, boilerplate: str) -> None:
        assert normalise_specifics(boilerplate, has_material_context=True) is None

    def test_an_over_long_answer_is_rejected_rather_than_truncated(self) -> None:
        """The column is 255 chars; truncating would store a half-sentence as fact."""
        assert (
            normalise_specifics("x" * MAX_SPECIFICS_LENGTH, has_material_context=True) is not None
        )
        assert normalise_specifics("x" * (MAX_SPECIFICS_LENGTH + 1), has_material_context=True) is (
            None
        )

    @pytest.mark.parametrize("answer", ["", "   ", None])
    def test_no_answer_is_no_specifics(self, answer: str | None) -> None:
        assert normalise_specifics(answer, has_material_context=True) is None


class TestMaterialContextComesFromTheRowToo:
    def test_pre_existing_alloy_is_enough_context_for_new_specifics(self, job: Job) -> None:
        """The model named no metal; the row already knows its grade, so specifics stick."""
        stock = make_stock(job, description="2.0X1200X3000 AL SHTPE", alloy="5005")

        with patch(LLM_BOUNDARY, return_value=llm_reply({"specifics": "H32 temper"})):
            auto_parse_stock_item(stock)

        stock.refresh_from_db()
        assert stock.specifics == "H32 temper"
        assert stock.metal_type is None
        assert stock.parsed_at is not None


class TestWhatTheParserIsToldAboutAStockRow:
    def test_the_row_reaches_the_model_as_its_own_description_and_price(self, job: Job) -> None:
        """Stock has no supplier fields, so the row's text is both name and description."""
        stock = make_stock(job, description=ALUMINIUM_SHEET, item_code="AL-5005", unit_cost="42.50")

        with patch(LLM_BOUNDARY, return_value=llm_reply({"metal_type": "aluminium"})) as completion:
            auto_parse_stock_item(stock)

        (prompt,), _kwargs = completion.call_args
        _examples, _, inputs = prompt.partition("INPUT DATA TO PARSE:")
        assert f"Product Name: {ALUMINIUM_SHEET}" in inputs
        assert f"Description: {ALUMINIUM_SHEET}" in inputs
        assert "Item Number: AL-5005" in inputs
        assert f"Variant Info: stock-{stock.id}" in inputs
        assert "Price: 42.50 each" in inputs


class TestReparsing:
    def test_an_already_parsed_row_is_left_alone(self, job: Job) -> None:
        stock = make_stock(job, description=ALUMINIUM_SHEET)
        with patch(LLM_BOUNDARY, return_value=llm_reply({"metal_type": "aluminium"})):
            auto_parse_stock_item(stock)
        stock.refresh_from_db()
        first_parsed_at = stock.parsed_at
        assert first_parsed_at is not None

        with patch(LLM_BOUNDARY) as completion:
            auto_parse_stock_item(stock)

        completion.assert_not_called()
        stock.refresh_from_db()
        assert stock.parsed_at == first_parsed_at

    def test_force_reruns_the_row_but_never_re_asks_the_model(self, job: Job) -> None:
        """force is about the row, not the mapping: the text was already priced once."""
        stock = make_stock(job, description=ALUMINIUM_SHEET)
        with patch(LLM_BOUNDARY, return_value=llm_reply({"metal_type": "aluminium"})):
            auto_parse_stock_item(stock)
        stock.refresh_from_db()
        first_attempted_at = stock.parser_attempted_at
        first_parsed_at = stock.parsed_at

        with patch(LLM_BOUNDARY) as completion:
            auto_parse_stock_item(stock, force=True)

        completion.assert_not_called()
        stock.refresh_from_db()
        # The run happened...
        assert stock.parser_attempted_at != first_attempted_at
        # ...but accepted nothing new, because the operator-wins rule only fills
        # blanks and there are none left. parsed_at dates the last ACCEPTED value.
        assert stock.parsed_at == first_parsed_at
        assert stock.metal_type == "aluminium"

    def test_force_fills_a_field_an_operator_has_since_cleared(self, job: Job) -> None:
        stock = make_stock(job, description=ALUMINIUM_SHEET)
        with patch(LLM_BOUNDARY, return_value=llm_reply({"metal_type": "aluminium"})):
            auto_parse_stock_item(stock)
        Stock.objects.filter(id=stock.id).update(metal_type=None)
        stock.refresh_from_db()
        first_parsed_at = stock.parsed_at

        with patch(LLM_BOUNDARY) as completion:
            auto_parse_stock_item(stock, force=True)

        completion.assert_not_called()
        stock.refresh_from_db()
        assert stock.metal_type == "aluminium"
        assert stock.parsed_at != first_parsed_at

    def test_the_confidence_the_model_gave_is_recorded(self, job: Job) -> None:
        stock = make_stock(job, description=ALUMINIUM_SHEET)
        reply = llm_reply({"metal_type": "aluminium", "confidence": 0.42})

        with patch(LLM_BOUNDARY, return_value=reply):
            auto_parse_stock_item(stock)

        stock.refresh_from_db()
        assert stock.parser_confidence == Decimal("0.42")
