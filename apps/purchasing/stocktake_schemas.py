"""Stocktake wire contracts: blank counts are explicitly nullable."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.core.schemas import (
    CountQuantity,
    InventoryQuantity,
    NonBlankText,
    NullableText,
    Quantity,
    ResponseSchema,
    UnitCost,
)


class StocktakeCreate(Schema):
    """StocktakeCreate wire contract."""

    stock_id: UUID | None = None


class StocktakeLineWrite(Schema):
    """StocktakeLineWrite wire contract."""

    id: UUID
    stock_id: UUID | None
    description: Annotated[NonBlankText, Field(max_length=255)]
    location: NullableText
    expected_version: Annotated[int, Field(ge=0)]
    expected_quantity: InventoryQuantity
    counted_quantity: CountQuantity | None
    unit_cost: UnitCost
    reason: NullableText


class StocktakeSave(Schema):
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


class StocktakeStockSearch(StocktakeSearch):
    """Bounded identity filtering also refreshes unsaved stock observations."""

    stock_ids: Annotated[list[UUID], Field(max_length=100)] = Field(default_factory=list)
