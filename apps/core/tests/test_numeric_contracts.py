"""Numeric wire bounds must agree with the Decimal values accepted by the server."""

from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from apps.core.schemas import CountQuantity, InventoryQuantity, UnitCost


def test_inventory_quantity_publishes_precision_and_signed_capacity() -> None:
    adapter = TypeAdapter(InventoryQuantity)
    assert adapter.json_schema() == {
        "type": "number",
        "minimum": -99999999.999,
        "maximum": 99999999.999,
        "multipleOf": 0.001,
    }
    assert adapter.validate_python("-0.125") == Decimal("-0.125")
    assert adapter.dump_json(Decimal("-0.125")) == b"-0.125"
    for invalid in ("100000000", "0.0001", "NaN", "Infinity"):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)


def test_count_and_cost_accept_explicit_zero_but_refuse_negative_values() -> None:
    count = TypeAdapter(CountQuantity)
    cost = TypeAdapter(UnitCost)
    assert count.json_schema()["minimum"] == 0
    assert cost.json_schema() == {
        "type": "number",
        "minimum": 0,
        "maximum": 99999999.99,
        "multipleOf": 0.01,
    }
    assert count.validate_python(0) == Decimal("0")
    assert cost.validate_python(0) == Decimal("0")
    with pytest.raises(ValidationError):
        count.validate_python("-0.001")
    for invalid in (None, "-0.01", "0.001", "100000000"):
        with pytest.raises(ValidationError):
            cost.validate_python(invalid)
