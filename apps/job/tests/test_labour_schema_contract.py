from __future__ import annotations

from typing import Any, ClassVar, cast

from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator


class LabourRateSchemaContractTests(TestCase):
    """The OpenAPI contract must advertise non-negative labour rates."""

    schemas: ClassVar[dict[str, Any]]

    @classmethod
    def setUpTestData(cls) -> None:
        generator = SchemaGenerator()  # type: ignore[no-untyped-call]  # drf-spectacular does not ship complete typing for tests.
        schema = generator.get_schema(public=True)  # type: ignore[no-untyped-call]  # Contract test intentionally exercises drf-spectacular.
        assert schema is not None
        cls.schemas = cast(dict[str, Any], schema["components"]["schemas"])

    def _property(self, schema_name: str, property_name: str) -> dict[str, Any]:
        return cast(
            dict[str, Any], self.schemas[schema_name]["properties"][property_name]
        )

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
