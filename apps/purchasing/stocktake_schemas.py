"""Stocktake wire contracts: blank counts are explicitly nullable."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.core.schemas import NonBlankText, NullableText, Quantity, ResponseSchema

CountQuantity = Annotated[Quantity, Field(ge=0, max_digits=11, decimal_places=3)]
CountCost = Annotated[Quantity, Field(ge=0, max_digits=10, decimal_places=2)]


class StocktakeCreate(Schema):
    """StocktakeCreate wire contract."""

    stock_id: UUID | None = None


class StocktakeVersion(Schema):
    """StocktakeVersion wire contract."""

    version: int


class StocktakeLineWrite(Schema):
    """StocktakeLineWrite wire contract."""

    id: UUID
    stock_id: UUID | None
    description: Annotated[NonBlankText, Field(max_length=255)]
    location: NullableText
    expected_version: int
    expected_quantity: Quantity
    counted_quantity: CountQuantity | None
    unit_cost: CountCost
    reason: NullableText


class StocktakeSave(StocktakeVersion):
    """StocktakeSave wire contract."""

    lines: list[StocktakeLineWrite]


class StocktakeLineOut(ResponseSchema):
    """StocktakeLineOut wire contract."""

    id: UUID
    stock_id: UUID | None
    description: str
    location: str | None
    expected_version: int
    expected_quantity: Quantity
    counted_quantity: Quantity | None
    counted_at: datetime | None
    unit_cost: Quantity
    reason: str | None
    difference: Quantity | None
    value: Quantity | None
    current_quantity: Quantity
    current_version: int
    stale: bool


class StocktakeSummary(ResponseSchema):
    """StocktakeSummary wire contract."""

    id: UUID
    version: int
    created_at: datetime
    posted_at: datetime | None
    author: str
    adjustment_job_id: UUID
    discrepancy_value: Quantity
    corrects_id: UUID | None


class StocktakeDetail(StocktakeSummary):
    """StocktakeDetail wire contract."""

    lines: list[StocktakeLineOut]


class StocktakeList(ResponseSchema):
    """StocktakeList wire contract."""

    results: list[StocktakeSummary]
    count: int


class StocktakeStockOut(ResponseSchema):
    """StocktakeStockOut wire contract."""

    id: UUID
    description: str
    location: str | None
    quantity: Quantity
    unit_cost: Quantity
    inventory_version: int


class StocktakeStockList(ResponseSchema):
    """StocktakeStockList wire contract."""

    results: list[StocktakeStockOut]
    count: int


class StocktakeSetup(ResponseSchema):
    """StocktakeSetup wire contract."""

    adjustment_job_id: UUID | None


class StocktakeSearch(Schema):
    """StocktakeSearch wire contract."""

    q: str = ""
    location: str = ""
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 50
