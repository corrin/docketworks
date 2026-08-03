"""Stock metadata parsing: the tasks, the acceptance rules, and the seam closure.

Ported from v1 ``apps/purchasing/tests/test_stock_metadata_tasks.py``. Every
test here asserts real business behaviour, so the whole file ports; the two v1
cases that covered the Xero item-sync call site are dropped, because that call
site (``apps/workflow/api/xero/transforms.py``) lands with the Phase 4 Xero
port and has nothing to attach to yet.

SEAM EVIDENCE. ``TestStockWriteSitesQueueTheParser`` is the closure of the
"STOCK METADATA PARSER SEAM" the purchasing slice left in
``apps/purchasing/services/stock_service.py``: it exercises all three stock
write sites through their real entry points (the create endpoint, the patch
endpoint, and a delivery-receipt allocation) and asserts the parser task is
actually queued — and, for the negative cases, that it is not.

The LLM is mocked at the one boundary — ``apps.quoting.tests.conftest``'s
``LLM_BOUNDARY``, which names ``apps.ai``'s gateway where the parser binds it —
and nowhere else, so prompting, mapping lookup, mapping persistence, the
acceptance rules and every stock write below run for real.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.models import AppError
from apps.job.models import Job
from apps.purchasing.models import Stock
from apps.purchasing.services import stock_service
from apps.purchasing.services.allocation_service import (
    AllocationMetadata,
    create_stock_from_allocation,
)
from apps.purchasing.tasks import (
    parse_stock_item_task,
    parse_unparsed_stock_items_task,
    queue_metadata_parse_if_eligible,
    stock_metadata_incomplete,
    stock_metadata_parse_eligible,
)
from apps.purchasing.tests.conftest import make_po_line, make_purchase_order, make_stock
from apps.quoting.models import ProductParsingMapping
from apps.quoting.services.stock_parser import auto_parse_stock_item
from apps.quoting.tests.conftest import LLM_BOUNDARY, llm_reply

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.purchasing.tests.urls"),
]

STOCK_URL = "/api/purchasing/stock/"

# The description v1's fixtures used: a real aluminium sheet code from the shop.
ALUMINIUM_SHEET = "2.0X1200X3000 5005H32 AL SHTPE"


@pytest.fixture
def unparsed_stock(stock_holding_job: Job) -> Stock:
    """A stock row with no metadata — the parser's whole reason to exist."""
    return make_stock(stock_holding_job, description=ALUMINIUM_SHEET, unit_cost="10.00")


class TestEligibility:
    def test_incomplete_detects_any_missing_metadata_field(self, stock_holding_job: Job) -> None:
        incomplete = make_stock(stock_holding_job, description=ALUMINIUM_SHEET)
        complete = make_stock(
            stock_holding_job,
            description=ALUMINIUM_SHEET,
            item_code="COMPLETE-5005",
            alloy="5005",
            metal_type="aluminium",
            specifics="H32 sheet",
        )

        assert stock_metadata_incomplete(incomplete) is True
        assert stock_metadata_incomplete(complete) is False

    def test_a_row_gets_one_attempt_unless_forced(self, stock_holding_job: Job) -> None:
        attempted = make_stock(
            stock_holding_job, description=ALUMINIUM_SHEET, parser_attempted_at=timezone.now()
        )
        never_attempted = make_stock(stock_holding_job, description=ALUMINIUM_SHEET)

        assert stock_metadata_parse_eligible(attempted) is False
        assert stock_metadata_parse_eligible(never_attempted) is True
        assert stock_metadata_parse_eligible(attempted, force=True) is True

    def test_an_already_parsed_row_is_not_reparsed(self, stock_holding_job: Job) -> None:
        parsed = make_stock(
            stock_holding_job, description=ALUMINIUM_SHEET, parsed_at=timezone.now()
        )

        assert stock_metadata_parse_eligible(parsed) is False
        assert stock_metadata_parse_eligible(parsed, force=True) is True


class TestParseStockItemTask:
    def test_parses_an_active_unparsed_row(self, unparsed_stock: Stock) -> None:
        with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
            parse_stock_item_task(str(unparsed_stock.id))

        parse.assert_called_once_with(unparsed_stock, force=False)

    def test_skips_an_already_parsed_row(self, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job, description=ALUMINIUM_SHEET, parsed_at=timezone.now())

        with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
            parse_stock_item_task(str(stock.id))

        parse.assert_not_called()

    def test_force_reparses_an_already_parsed_row(self, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job, description=ALUMINIUM_SHEET, parsed_at=timezone.now())

        with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
            parse_stock_item_task(str(stock.id), force=True)

        parse.assert_called_once_with(stock, force=True)

    def test_skips_a_row_that_already_had_its_attempt(self, stock_holding_job: Job) -> None:
        stock = make_stock(
            stock_holding_job, description=ALUMINIUM_SHEET, parser_attempted_at=timezone.now()
        )

        with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
            parse_stock_item_task(str(stock.id))

        parse.assert_not_called()

    def test_skips_an_inactive_row(self, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job, description=ALUMINIUM_SHEET, is_active=False)

        with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
            parse_stock_item_task(str(stock.id))

        parse.assert_not_called()

    def test_skips_a_row_whose_metadata_is_already_complete(self, stock_holding_job: Job) -> None:
        stock = make_stock(
            stock_holding_job,
            description=ALUMINIUM_SHEET,
            metal_type="aluminium",
            alloy="5005",
            specifics="H32 sheet",
        )

        with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
            parse_stock_item_task(str(stock.id))

        parse.assert_not_called()

    def test_a_crash_is_persisted_with_the_stock_row_and_re_raised(
        self, unparsed_stock: Stock
    ) -> None:
        """ADR 0019: without the stock id, a Gemini failure is unjoinable to its row."""
        with (
            patch(
                "apps.purchasing.tasks.auto_parse_stock_item",
                side_effect=RuntimeError("Gemini is down"),
            ),
            pytest.raises(RuntimeError, match="Gemini is down"),
        ):
            parse_stock_item_task(str(unparsed_stock.id), force=True)

        error = AppError.objects.get(message="Gemini is down")
        assert error.data is not None
        assert error.data["stock_id"] == str(unparsed_stock.id)
        assert error.data["force"] is True


class TestCatchUpBatch:
    def test_queues_only_incomplete_never_attempted_rows_up_to_the_limit(
        self, stock_holding_job: Job
    ) -> None:
        first = make_stock(stock_holding_job, description=ALUMINIUM_SHEET, item_code="FIRST")
        second = make_stock(stock_holding_job, description=ALUMINIUM_SHEET, item_code="SECOND")
        make_stock(
            stock_holding_job,
            description=ALUMINIUM_SHEET,
            item_code="COMPLETE",
            alloy="5005",
            metal_type="aluminium",
            specifics="H32 sheet",
        )
        make_stock(
            stock_holding_job,
            description=ALUMINIUM_SHEET,
            item_code="PARSED",
            parsed_at=timezone.now(),
        )
        make_stock(
            stock_holding_job,
            description=ALUMINIUM_SHEET,
            item_code="ATTEMPTED",
            parser_attempted_at=timezone.now(),
        )

        with patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay:
            parse_unparsed_stock_items_task(limit=1)

        delay.assert_called_once_with(str(first.id))
        assert str(second.id) not in [call.args[0] for call in delay.call_args_list]

    def test_a_row_the_model_could_not_answer_is_never_requeued(
        self, unparsed_stock: Stock
    ) -> None:
        """The whole point of parser_attempted_at: one LLM call per row, ever."""
        with patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay:
            parse_unparsed_stock_items_task(limit=50)
        delay.assert_called_once_with(str(unparsed_stock.id))

        with patch(LLM_BOUNDARY, return_value="no json here"):
            parse_stock_item_task(str(unparsed_stock.id))

        unparsed_stock.refresh_from_db()
        assert unparsed_stock.parser_attempted_at is not None
        assert unparsed_stock.parsed_at is None

        with patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay:
            parse_unparsed_stock_items_task(limit=50)
        delay.assert_not_called()

    def test_a_crash_queueing_the_batch_is_persisted_with_its_context(
        self,
        unparsed_stock: Stock,  # noqa: ARG002 -- a row to queue, so delay is reached
    ) -> None:
        with (
            patch(
                "apps.purchasing.tasks.parse_stock_item_task.delay",
                side_effect=RuntimeError("Broker is down"),
            ),
            pytest.raises(RuntimeError, match="Broker is down"),
        ):
            parse_unparsed_stock_items_task(limit=5)

        error = AppError.objects.get(message="Broker is down")
        assert error.data is not None
        assert error.data["task"] == "parse_unparsed_stock_items_task"
        assert error.data["limit"] == 5


class TestAcceptanceRules:
    def test_accepted_metadata_is_saved_and_stamps_both_timestamps(
        self, unparsed_stock: Stock
    ) -> None:
        reply = llm_reply(
            {
                "metal_type": "aluminium",
                "alloy": "5005",
                "specifics": "H32 temper",
                "confidence": 0.95,
            }
        )

        with patch(LLM_BOUNDARY, return_value=reply):
            auto_parse_stock_item(unparsed_stock)

        unparsed_stock.refresh_from_db()
        assert unparsed_stock.metal_type == "aluminium"
        assert unparsed_stock.alloy == "5005"
        assert unparsed_stock.specifics == "H32 temper"
        assert unparsed_stock.parser_confidence == Decimal("0.95")
        assert unparsed_stock.parser_attempted_at is not None
        assert unparsed_stock.parsed_at == unparsed_stock.parser_attempted_at

    def test_american_metal_spelling_is_normalised(self, unparsed_stock: Stock) -> None:
        reply = llm_reply({"metal_type": "aluminum", "alloy": "5005", "specifics": "H32 temper"})

        with patch(LLM_BOUNDARY, return_value=reply):
            auto_parse_stock_item(unparsed_stock)

        unparsed_stock.refresh_from_db()
        assert unparsed_stock.metal_type == "aluminium"

    def test_an_invented_alloy_is_rejected(self, stock_holding_job: Job) -> None:
        """Gemini invents grades; only alloys named in the row's own text stick."""
        stock = make_stock(stock_holding_job, description="2.0X1200X3000 AL SHTPE")
        reply = llm_reply({"metal_type": "aluminium", "alloy": "5005", "specifics": "Sheet"})

        with patch(LLM_BOUNDARY, return_value=reply):
            auto_parse_stock_item(stock)

        stock.refresh_from_db()
        assert stock.metal_type == "aluminium"
        assert stock.alloy is None
        assert stock.specifics == "Sheet"

    def test_a_metal_type_outside_the_choices_is_rejected_entirely(
        self, stock_holding_job: Job
    ) -> None:
        stock = make_stock(stock_holding_job, description="Round Plug 55mm")
        reply = llm_reply({"metal_type": "plastic", "specifics": "Round Plug"})

        with patch(LLM_BOUNDARY, return_value=reply):
            auto_parse_stock_item(stock)

        stock.refresh_from_db()
        assert stock.metal_type is None
        assert stock.alloy is None
        # Without material context, specifics is noise too.
        assert stock.specifics is None
        assert stock.parser_attempted_at is not None
        assert stock.parsed_at is None

    def test_generic_specifics_boilerplate_is_rejected(self, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job, description="5005 aluminium offcut")
        reply = llm_reply({"metal_type": "aluminium", "alloy": "5005", "specifics": "Service item"})

        with patch(LLM_BOUNDARY, return_value=reply):
            auto_parse_stock_item(stock)

        stock.refresh_from_db()
        assert stock.specifics is None
        assert stock.metal_type == "aluminium"

    def test_operator_supplied_metadata_wins_over_the_model(self, stock_holding_job: Job) -> None:
        stock = make_stock(
            stock_holding_job,
            description=ALUMINIUM_SHEET,
            metal_type="mild_steel",
            specifics="Operator note",
        )
        reply = llm_reply({"metal_type": "aluminium", "alloy": "5005", "specifics": "H32 temper"})

        with patch(LLM_BOUNDARY, return_value=reply):
            auto_parse_stock_item(stock)

        stock.refresh_from_db()
        assert stock.metal_type == "mild_steel"
        assert stock.specifics == "Operator note"
        assert stock.alloy == "5005"

    def test_an_unusable_reply_records_the_attempt_but_no_parse(
        self, unparsed_stock: Stock
    ) -> None:
        with patch(
            LLM_BOUNDARY,
            return_value="I could not read that.",
        ):
            auto_parse_stock_item(unparsed_stock)

        unparsed_stock.refresh_from_db()
        assert unparsed_stock.parser_attempted_at is not None
        assert unparsed_stock.parsed_at is None
        assert stock_metadata_parse_eligible(unparsed_stock) is False

    def test_a_failed_call_leaves_the_row_eligible_to_retry(self, unparsed_stock: Stock) -> None:
        """An outage must not permanently disqualify a row (unlike a bad answer)."""
        with (
            patch(
                LLM_BOUNDARY,
                side_effect=TimeoutError("Gemini timeout"),
            ),
            pytest.raises(TimeoutError),
        ):
            auto_parse_stock_item(unparsed_stock)

        unparsed_stock.refresh_from_db()
        assert unparsed_stock.parser_attempted_at is None
        assert stock_metadata_parse_eligible(unparsed_stock) is True

    def test_the_mapping_is_reused_on_the_next_row_with_the_same_description(
        self, stock_holding_job: Job
    ) -> None:
        """The mapping table is why the LLM is called once per distinct text."""
        first = make_stock(stock_holding_job, description=ALUMINIUM_SHEET, item_code="A")
        second = make_stock(stock_holding_job, description=ALUMINIUM_SHEET, item_code="B")
        reply = llm_reply({"metal_type": "aluminium", "alloy": "5005", "specifics": "H32 temper"})

        with patch(LLM_BOUNDARY, return_value=reply) as completion:
            auto_parse_stock_item(first)
            auto_parse_stock_item(second)

        assert completion.call_count == 1
        second.refresh_from_db()
        assert second.metal_type == "aluminium"
        assert ProductParsingMapping.objects.count() == 1


class TestStockWriteSitesQueueTheParser:
    """SEAM CLOSURE: every stock write enqueues the metadata parser."""

    def test_the_create_endpoint_queues_a_parse(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- resolves Stock.get_stock_holding_job()
        django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    ) -> None:
        with (
            patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.post(
                STOCK_URL,
                data={
                    "description": ALUMINIUM_SHEET,
                    "quantity": "1",
                    "unit_cost": "10.00",
                    "source": "manual",
                },
                content_type="application/json",
            )

        assert response.status_code == 201, response.content
        stock = Stock.objects.get(description=ALUMINIUM_SHEET)
        delay.assert_called_once_with(str(stock.id), force=False)

    def test_the_create_endpoint_skips_the_parse_when_metadata_is_supplied(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- resolves Stock.get_stock_holding_job()
        django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    ) -> None:
        with (
            patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.post(
                STOCK_URL,
                data={
                    "description": ALUMINIUM_SHEET,
                    "quantity": "1",
                    "unit_cost": "10.00",
                    "source": "manual",
                    "metal_type": "aluminium",
                    "alloy": "5005",
                    "specifics": "H32 sheet",
                },
                content_type="application/json",
            )

        assert response.status_code == 201, response.content
        delay.assert_not_called()

    def test_the_patch_endpoint_queues_a_parse(
        self,
        client: Client,
        stock_holding_job: Job,
        django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    ) -> None:
        stock = make_stock(stock_holding_job, description="Old description")

        with (
            patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.patch(
                f"{STOCK_URL}{stock.id}/",
                data={"description": ALUMINIUM_SHEET},
                content_type="application/json",
            )

        assert response.status_code == 200, response.content
        delay.assert_called_once_with(str(stock.id), force=False)

    def test_a_delivery_receipt_allocation_queues_a_parse(
        self,
        stock_holding_job: Job,
        office_staff: Staff,
        supplier: Company,
        django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    ) -> None:
        po = make_purchase_order(supplier=supplier, created_by=office_staff)
        line = make_po_line(po, description=ALUMINIUM_SHEET, quantity="1.00", unit_cost="10.00")

        with (
            patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            stock = create_stock_from_allocation(
                line=line,
                job=stock_holding_job,
                qty=Decimal("1.00"),
                metadata=AllocationMetadata.from_line(line),
                retail_rate_pct=Decimal("20.00"),
            )

        delay.assert_called_once_with(str(stock.id), force=False)

    def test_a_rolled_back_write_never_reaches_a_worker(
        self,
        stock_holding_job: Job,  # noqa: ARG002 -- resolves Stock.get_stock_holding_job()
        django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    ) -> None:
        """on_commit is why: the worker must not see an id the caller rolled back.

        Both halves are asserted, because "no task was queued" on its own would
        also pass if the write site had forgotten to enqueue at all: the
        callback IS registered by the write, and it does NOT run while the
        surrounding transaction is unfinished.
        """
        with (
            patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay,
            django_capture_on_commit_callbacks(execute=False) as callbacks,
        ):
            stock_service.create_stock(
                {
                    "description": ALUMINIUM_SHEET,
                    "quantity": Decimal("1"),
                    "unit_cost": Decimal("10.00"),
                }
            )

        assert len(callbacks) == 1
        delay.assert_not_called()

    def test_the_eligibility_guard_is_one_implementation(self, stock_holding_job: Job) -> None:
        complete = make_stock(
            stock_holding_job,
            description=ALUMINIUM_SHEET,
            metal_type="aluminium",
            alloy="5005",
            specifics="H32 sheet",
        )
        incomplete = make_stock(stock_holding_job, description=ALUMINIUM_SHEET)

        assert queue_metadata_parse_if_eligible(complete) is False
        assert queue_metadata_parse_if_eligible(incomplete) is True
