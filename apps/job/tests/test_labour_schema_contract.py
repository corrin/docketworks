from __future__ import annotations

from typing import ClassVar

from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator

from apps.workflow.api.types import JsonObject, JsonValue


def _as_object(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object, got {type(value).__name__}")
    return value


class LabourRateSchemaContractTests(TestCase):
    """The OpenAPI contract must advertise non-negative labour rates."""

    schemas: ClassVar[JsonObject]

    @classmethod
    def setUpTestData(cls) -> None:
        schema = SchemaGenerator().get_schema(public=True)
        if schema is None:
            raise RuntimeError("schema generation returned None")
        cls.schemas = _as_object(_as_object(schema["components"])["schemas"])

    def _property(self, schema_name: str, property_name: str) -> JsonObject:
        schema = _as_object(self.schemas[schema_name])
        return _as_object(_as_object(schema["properties"])[property_name])

    def test_labour_subtype_default_rate_is_non_negative(self) -> None:
        for schema_name in [
            "LabourSubtype",
            "LabourSubtypeManage",
            "LabourSubtypeManageRequest",
            "PatchedLabourSubtypeManageRequest",
        ]:
            with self.subTest(schema_name=schema_name):
                self.assertEqual(
                    self._property(schema_name, "default_charge_out_rate")["minimum"],
                    0,
                )

    def test_job_labour_rate_is_non_negative(self) -> None:
        for schema_name in ["JobLabourRate", "JobLabourRateUpdateRequest"]:
            with self.subTest(schema_name=schema_name):
                self.assertEqual(
                    self._property(schema_name, "charge_out_rate")["minimum"],
                    0,
                )
