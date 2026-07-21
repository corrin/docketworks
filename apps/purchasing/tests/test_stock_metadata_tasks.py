"""Regression coverage for async stock metadata parsing."""

from collections.abc import Callable
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.purchasing.services.delivery_receipt_service import (
    _create_stock_from_allocation,
)
from apps.purchasing.tasks import (
    parse_stock_item_task,
    parse_unparsed_stock_items_task,
    stock_metadata_incomplete,
    stock_metadata_parse_eligible,
)
from apps.quoting.services.stock_parser import auto_parse_stock_item
from apps.workflow.api.xero.transforms import transform_stock

_transform_stock = cast(Callable[[Any, str], tuple[Stock, str]], transform_stock)


def _stock(**overrides: Any) -> Stock:
    defaults = dict(
        description="2.0X1200X3000 5005H32 AL SHTPE",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
        source="product_catalog",
        is_active=True,
    )
    defaults.update(overrides)
    return Stock.objects.create(**defaults)


def _staff() -> Staff:
    staff = Staff.objects.create(
        email="stock-meta@example.test",
        first_name="Stock",
        last_name="Parser",
        password_needs_reset=False,
        is_office_staff=True,
    )
    staff.set_password("pw")
    staff.save()
    return staff


def _xero_item(**overrides: Any) -> SimpleNamespace:
    defaults = {
        "code": "SHT-2.0-AL5005-1200X3000",
        "name": "2.0X1200X3000 5005H32 AL SHTPE",
        "is_tracked_as_inventory": True,
        "updated_date_utc": timezone.now(),
        "quantity_on_hand": Decimal("3.00"),
        "sales_details": SimpleNamespace(unit_price=Decimal("22.00")),
        "purchase_details": SimpleNamespace(unit_price=Decimal("11.00")),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.django_db
def test_stock_metadata_incomplete_detects_missing_fields() -> None:
    incomplete = _stock(alloy="", metal_type="unspecified", specifics="")
    complete = _stock(
        item_code="COMPLETE-5005",
        alloy="5005",
        metal_type="aluminium",
        specifics="H32 sheet",
    )

    assert stock_metadata_incomplete(incomplete) is True
    assert stock_metadata_incomplete(complete) is False


@pytest.mark.django_db
def test_stock_metadata_parse_eligible_excludes_prior_attempts() -> None:
    attempted = _stock(parser_attempted_at=timezone.now())
    never_attempted = _stock()

    assert stock_metadata_parse_eligible(attempted) is False
    assert stock_metadata_parse_eligible(never_attempted) is True
    assert stock_metadata_parse_eligible(attempted, force=True) is True


@pytest.mark.django_db
def test_parse_stock_item_task_parses_active_unparsed_stock() -> None:
    stock = _stock()

    with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
        parse_stock_item_task(str(stock.id))

    parse.assert_called_once_with(stock, force=False)


@pytest.mark.django_db
def test_parse_stock_item_task_skips_already_parsed_stock_without_force() -> None:
    stock = _stock(parsed_at=timezone.now())

    with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
        parse_stock_item_task(str(stock.id))

    parse.assert_not_called()


@pytest.mark.django_db
def test_parse_stock_item_task_force_reparses_already_parsed_stock() -> None:
    stock = _stock(parsed_at=timezone.now())

    with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
        parse_stock_item_task(str(stock.id), force=True)

    parse.assert_called_once_with(stock, force=True)


@pytest.mark.django_db
def test_parse_stock_item_task_skips_already_attempted_stock_without_force() -> None:
    stock = _stock(parser_attempted_at=timezone.now())

    with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
        parse_stock_item_task(str(stock.id))

    parse.assert_not_called()


@pytest.mark.django_db
def test_parse_stock_item_task_force_reparses_already_attempted_stock() -> None:
    stock = _stock(parser_attempted_at=timezone.now())

    with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
        parse_stock_item_task(str(stock.id), force=True)

    parse.assert_called_once_with(stock, force=True)


@pytest.mark.django_db
def test_parse_stock_item_task_skips_inactive_stock() -> None:
    stock = _stock(is_active=False)

    with patch("apps.purchasing.tasks.auto_parse_stock_item") as parse:
        parse_stock_item_task(str(stock.id))

    parse.assert_not_called()


@pytest.mark.django_db
def test_parse_unparsed_stock_items_task_queues_bounded_incomplete_batch() -> None:
    first = _stock(item_code="FIRST")
    second = _stock(item_code="SECOND")
    _stock(
        item_code="COMPLETE",
        alloy="5005",
        metal_type="aluminium",
        specifics="H32 sheet",
    )
    _stock(item_code="PARSED", parsed_at=timezone.now())
    _stock(item_code="ATTEMPTED", parser_attempted_at=timezone.now())

    with patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay:
        parse_unparsed_stock_items_task(limit=1)

    delay.assert_called_once_with(str(first.id))
    assert str(second.id) not in [call.args[0] for call in delay.call_args_list]


@pytest.mark.django_db
def test_auto_parse_stock_item_saves_valid_metadata_and_attempt() -> None:
    stock = _stock(metal_type="unspecified", alloy="", specifics="")
    parsed_data = {
        "metal_type": "aluminium",
        "alloy": "5005",
        "specifics": "H32 temper",
        "confidence": "0.95",
        "parser_version": "1.1.0",
    }

    with patch("apps.quoting.services.stock_parser.ProductParser") as parser_class:
        parser_class.return_value.parse_product.return_value = (parsed_data, False)
        auto_parse_stock_item(stock)

    stock.refresh_from_db()
    assert stock.parser_attempted_at is not None
    assert stock.parsed_at == stock.parser_attempted_at
    assert stock.metal_type == "aluminium"
    assert stock.alloy == "5005"
    assert stock.specifics == "H32 temper"
    assert stock.parser_confidence == Decimal("0.95")


@pytest.mark.django_db
def test_auto_parse_stock_item_normalises_gemini_american_metal_spelling() -> None:
    stock = _stock(metal_type="unspecified", alloy="", specifics="")
    parsed_data = {
        "metal_type": "aluminum",
        "alloy": "5005",
        "specifics": "H32 temper",
        "confidence": "0.95",
        "parser_version": "1.1.0",
    }

    with patch("apps.quoting.services.stock_parser.ProductParser") as parser_class:
        parser_class.return_value.parse_product.return_value = (parsed_data, False)
        auto_parse_stock_item(stock)

    stock.refresh_from_db()
    assert stock.metal_type == "aluminium"


@pytest.mark.django_db
def test_auto_parse_stock_item_records_attempt_without_retrying_empty_result() -> None:
    stock = _stock(metal_type="unspecified", alloy="", specifics="")

    with patch("apps.quoting.services.stock_parser.ProductParser") as parser_class:
        parser_class.return_value.parse_product.return_value = ({}, False)
        auto_parse_stock_item(stock)

    stock.refresh_from_db()
    assert stock.parser_attempted_at is not None
    assert stock.parsed_at is None
    assert stock_metadata_parse_eligible(stock) is False


@pytest.mark.django_db
def test_auto_parse_stock_item_does_not_record_attempt_on_parser_exception() -> None:
    stock = _stock(metal_type="unspecified", alloy="", specifics="")

    with (
        patch("apps.quoting.services.stock_parser.ProductParser") as parser_class,
        patch("apps.quoting.services.stock_parser.persist_app_error") as persist_error,
    ):
        persist_error.return_value.id = uuid4()
        parser_class.return_value.parse_product.side_effect = TimeoutError(
            "Gemini timeout"
        )
        with pytest.raises(TimeoutError):
            auto_parse_stock_item(stock)

    stock.refresh_from_db()
    assert stock.parser_attempted_at is None
    assert stock_metadata_parse_eligible(stock) is True


@pytest.mark.django_db
def test_failed_gemini_parse_is_not_requeued_by_backfill() -> None:
    stock = _stock(metal_type="unspecified", alloy="", specifics="")

    with patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay:
        parse_unparsed_stock_items_task(limit=50)

    delay.assert_called_once_with(str(stock.id))

    with patch("apps.quoting.services.stock_parser.ProductParser") as parser_class:
        parser_class.return_value.parse_product.return_value = ({}, False)
        parse_stock_item_task(str(stock.id))

    stock.refresh_from_db()
    assert stock.parser_attempted_at is not None
    assert stock.parsed_at is None

    with patch("apps.purchasing.tasks.parse_stock_item_task.delay") as delay:
        parse_unparsed_stock_items_task(limit=50)

    delay.assert_not_called()


@pytest.mark.django_db
def test_auto_parse_stock_item_rejects_hallucinated_alloy() -> None:
    stock = _stock(description="2.0X1200X3000 AL SHTPE", alloy="")
    parsed_data = {
        "metal_type": "aluminium",
        "alloy": "5005",
        "specifics": "Sheet",
        "confidence": "0.95",
        "parser_version": "1.1.0",
    }

    with patch("apps.quoting.services.stock_parser.ProductParser") as parser_class:
        parser_class.return_value.parse_product.return_value = (parsed_data, False)
        auto_parse_stock_item(stock)

    stock.refresh_from_db()
    assert stock.metal_type == "aluminium"
    assert stock.alloy == ""
    assert stock.specifics == "Sheet"


@pytest.mark.django_db
def test_auto_parse_stock_item_rejects_invalid_metal_type() -> None:
    stock = _stock(
        description="Round Plug 55mm",
        metal_type="unspecified",
        alloy="",
        specifics="",
    )
    parsed_data = {
        "metal_type": "plastic",
        "alloy": None,
        "specifics": "Round Plug",
        "confidence": "0.88",
        "parser_version": "1.1.0",
    }

    with patch("apps.quoting.services.stock_parser.ProductParser") as parser_class:
        parser_class.return_value.parse_product.return_value = (parsed_data, False)
        auto_parse_stock_item(stock)

    stock.refresh_from_db()
    assert stock.parser_attempted_at is not None
    assert stock.parsed_at is None
    assert stock.metal_type == "unspecified"
    assert stock.alloy == ""
    assert stock.specifics == ""


@pytest.mark.django_db
def test_xero_stock_create_enqueues_metadata_parse() -> None:
    xero_id = str(uuid4())
    with patch(
        "apps.workflow.api.xero.transforms.enqueue_stock_metadata_parse"
    ) as enqueue:
        stock, status = _transform_stock(_xero_item(), xero_id)

    assert status == "created"
    enqueue.assert_called_once_with(stock.id)


@pytest.mark.django_db
def test_xero_stock_update_enqueues_when_description_changes() -> None:
    xero_id = uuid4()
    stock = _stock(
        xero_id=xero_id,
        item_code="OLD-CODE",
        description="Old description",
    )

    with patch(
        "apps.workflow.api.xero.transforms.enqueue_stock_metadata_parse"
    ) as enqueue:
        updated, status = _transform_stock(
            _xero_item(),
            str(xero_id),
        )

    assert updated.id == stock.id
    assert status != "unchanged"
    enqueue.assert_called_once_with(stock.id)


@pytest.mark.django_db
def test_stock_viewset_create_enqueues_metadata_parse() -> None:
    api = APIClient()
    api.force_authenticate(user=_staff())

    with patch(
        "apps.purchasing.views.stock_viewset.enqueue_stock_metadata_parse"
    ) as enqueue:
        response = api.post(
            "/api/purchasing/stock/",
            {
                "description": "2.0X1200X3000 5005H32 AL SHTPE",
                "quantity": "1.00",
                "unit_cost": "10.00",
                "source": "manual",
            },
            format="json",
        )

    assert response.status_code == 201, response.content
    stock = Stock.objects.get(description="2.0X1200X3000 5005H32 AL SHTPE")
    enqueue.assert_called_once_with(stock.id)


@pytest.fixture
def company_defaults(db: None) -> None:
    # Job.save -> generate_job_number -> CompanyDefaults.get_solo(); the
    # singleton cannot be lazily created (shop_company is NOT NULL).
    call_command("loaddata", "company_defaults")


@pytest.mark.django_db
def test_delivery_receipt_stock_creation_enqueues_metadata_parse(
    company_defaults: None,
) -> None:
    staff = _staff()
    company = Company.objects.create(
        name="Receipt Stock Company",
        xero_last_modified=timezone.now(),
    )
    job = Job.objects.create(company=company, name="Receipt Stock Job", staff=staff)
    po = PurchaseOrder.objects.create(po_number="PO-STOCK-META")
    line = PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="2.0X1200X3000 5005H32 AL SHTPE",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
    )

    with patch(
        "apps.purchasing.services.delivery_receipt_service.enqueue_stock_metadata_parse"
    ) as enqueue:
        stock = _create_stock_from_allocation(
            purchase_order=po,
            line=line,
            job=job,
            qty=Decimal("1.00"),
            metadata={},
            retail_rate_pct=Decimal("20.00"),
        )

    enqueue.assert_called_once_with(stock.id)
