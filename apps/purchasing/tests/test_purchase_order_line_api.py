"""PO-line writes preserve NULL as the only representation of unset text."""

from decimal import Decimal

from rest_framework import status

from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.serializers import (
    PurchaseOrderCreateSerializer,
    PurchaseOrderLineCreateSerializer,
    PurchaseOrderLineUpdateSerializer,
    PurchaseOrderUpdateSerializer,
)
from apps.testing import BaseAPITestCase
from apps.workflow.models import AppError

NULLABLE_LINE_FIELDS = (
    "item_code",
    "metal_type",
    "alloy",
    "specifics",
    "location",
    "dimensions",
)


class PurchaseOrderLineAPIContractTests(BaseAPITestCase):
    """Guard the API boundary that previously turned blank item codes into 409s."""

    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(self.test_staff)

    def test_create_and_update_contracts_accept_null_and_reject_blank(self) -> None:
        """Create/update must agree so one path cannot reintroduce blank DB writes."""
        serializer_classes = (
            PurchaseOrderLineCreateSerializer,
            PurchaseOrderLineUpdateSerializer,
        )

        for serializer_class in serializer_classes:
            for field_name in NULLABLE_LINE_FIELDS:
                with self.subTest(
                    serializer=serializer_class.__name__, field=field_name
                ):
                    nullable = serializer_class(data={field_name: None})
                    self.assertTrue(nullable.is_valid(), nullable.errors)

                    blank = serializer_class(data={field_name: ""})
                    self.assertFalse(blank.is_valid())
                    self.assertIn(field_name, blank.errors)

    def test_create_and_update_contracts_enforce_model_text_limits(self) -> None:
        """Oversized line text must be rejected before it reaches the database."""
        serializer_classes = (
            PurchaseOrderLineCreateSerializer,
            PurchaseOrderLineUpdateSerializer,
        )
        field_limits = (
            ("description", 200),
            ("item_code", 50),
            ("alloy", 50),
        )

        for serializer_class in serializer_classes:
            for field_name, max_length in field_limits:
                with self.subTest(
                    serializer=serializer_class.__name__, field=field_name
                ):
                    at_limit = serializer_class(data={field_name: "x" * max_length})
                    self.assertTrue(at_limit.is_valid(), at_limit.errors)

                    oversized = serializer_class(
                        data={field_name: "x" * (max_length + 1)}
                    )
                    self.assertFalse(oversized.is_valid())
                    self.assertIn(field_name, oversized.errors)

    def test_tbc_line_without_item_code_can_be_created_then_confirmed(self) -> None:
        """A full PATCH must confirm a free-description TBC line without a 409."""
        create_response = self.client.post(
            "/api/purchasing/purchase-orders/",
            {
                "lines": [
                    {
                        "description": "Zalmax 25x25x1.6 SHS",
                        "quantity": "2.00",
                        "unit_cost": None,
                        "price_tbc": True,
                        "item_code": None,
                        "metal_type": "mild_steel",
                        "alloy": "Zalmax",
                        "specifics": "1.6 mm wall",
                        "location": "Steel rack",
                        "dimensions": "25x25x1.6",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        purchase_order = PurchaseOrder.objects.get(id=create_response.json()["id"])
        self.assertIsNone(purchase_order.reference)
        line = purchase_order.po_lines.get()
        self.assertIsNone(line.item_code)
        self.assertEqual(line.metal_type, "mild_steel")
        self.assertEqual(line.alloy, "Zalmax")
        self.assertEqual(line.specifics, "1.6 mm wall")
        self.assertEqual(line.location, "Steel rack")
        self.assertEqual(line.dimensions, "25x25x1.6")

        detail_url = f"/api/purchasing/purchase-orders/{purchase_order.id}/"
        detail_response = self.client.get(detail_url)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)

        patch_response = self.client.patch(
            detail_url,
            {
                "lines": [
                    {
                        "id": str(line.id),
                        "job_id": None,
                        "description": line.description,
                        "quantity": "2.00",
                        "unit_cost": "19.50",
                        "price_tbc": False,
                        **{field_name: None for field_name in NULLABLE_LINE_FIELDS},
                    }
                ]
            },
            format="json",
            HTTP_IF_MATCH=detail_response["ETag"],
        )

        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        line.refresh_from_db()
        self.assertEqual(line.unit_cost, Decimal("19.50"))
        self.assertFalse(line.price_tbc)
        for field_name in NULLABLE_LINE_FIELDS:
            with self.subTest(field=field_name):
                self.assertIsNone(getattr(line, field_name))

        refreshed_response = self.client.get(detail_url)
        self.assertEqual(refreshed_response.status_code, status.HTTP_200_OK)
        response_line = refreshed_response.json()["lines"][0]
        for field_name in NULLABLE_LINE_FIELDS:
            with self.subTest(response_field=field_name):
                self.assertIsNone(response_line[field_name])

    def test_patch_rejects_blank_item_code_before_the_database(self) -> None:
        """Blank item codes must be a validation 400, not an IntegrityError/409."""
        purchase_order = PurchaseOrder.objects.create(
            po_number="PO-BLANK-ITEM-CODE",
            created_by=self.test_staff,
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=purchase_order,
            description="Free-description line",
            quantity=Decimal("1"),
            unit_cost=None,
            price_tbc=True,
            item_code=None,
        )
        detail_url = f"/api/purchasing/purchase-orders/{purchase_order.id}/"
        detail_response = self.client.get(detail_url)

        response = self.client.patch(
            detail_url,
            {
                "lines": [
                    {
                        "id": str(line.id),
                        "description": line.description,
                        "quantity": "1.00",
                        "unit_cost": "25.00",
                        "price_tbc": False,
                        "item_code": "",
                    }
                ]
            },
            format="json",
            HTTP_IF_MATCH=detail_response["ETag"],
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("item_code", str(response.json()["details"]))
        self.assertEqual(AppError.objects.count(), 0)
        line.refresh_from_db()
        self.assertIsNone(line.unit_cost)
        self.assertTrue(line.price_tbc)
        self.assertIsNone(line.item_code)


class PurchaseOrderReferenceAPIContractTests(BaseAPITestCase):
    """Guard optional references against the empty-string database constraint."""

    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(self.test_staff)

    def test_create_and_update_contracts_accept_null_and_reject_blank(self) -> None:
        """Both PO write paths must use NULL, not blank, for an unset reference."""
        for serializer_class in (
            PurchaseOrderCreateSerializer,
            PurchaseOrderUpdateSerializer,
        ):
            with self.subTest(serializer=serializer_class.__name__, value=None):
                nullable = serializer_class(data={"reference": None})
                self.assertTrue(nullable.is_valid(), nullable.errors)

            with self.subTest(serializer=serializer_class.__name__, value=""):
                blank = serializer_class(data={"reference": ""})
                self.assertFalse(blank.is_valid())
                self.assertIn("reference", blank.errors)

    def test_create_and_update_contracts_enforce_reference_limit(self) -> None:
        """Oversized references must be rejected before database persistence."""
        for serializer_class in (
            PurchaseOrderCreateSerializer,
            PurchaseOrderUpdateSerializer,
        ):
            with self.subTest(serializer=serializer_class.__name__):
                at_limit = serializer_class(data={"reference": "x" * 100})
                self.assertTrue(at_limit.is_valid(), at_limit.errors)

                oversized = serializer_class(data={"reference": "x" * 101})
                self.assertFalse(oversized.is_valid())
                self.assertIn("reference", oversized.errors)

    def test_create_without_reference_and_patch_clear_both_persist_null(self) -> None:
        """Forgetting or clearing a reference must succeed instead of reaching a CHECK."""
        create_response = self.client.post(
            "/api/purchasing/purchase-orders/",
            {"reference": None},
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        purchase_order = PurchaseOrder.objects.get(id=create_response.json()["id"])
        self.assertIsNone(purchase_order.reference)

        purchase_order_with_reference = PurchaseOrder.objects.create(
            po_number="PO-REFERENCE-TO-CLEAR",
            reference="Reference to clear",
            created_by=self.test_staff,
        )
        detail_url = (
            f"/api/purchasing/purchase-orders/{purchase_order_with_reference.id}/"
        )
        detail_response = self.client.get(detail_url)
        patch_response = self.client.patch(
            detail_url,
            {"reference": None},
            format="json",
            HTTP_IF_MATCH=detail_response["ETag"],
        )

        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        purchase_order_with_reference.refresh_from_db()
        self.assertIsNone(purchase_order_with_reference.reference)
        refreshed_response = self.client.get(detail_url)
        self.assertIsNone(refreshed_response.json()["reference"])

    def test_blank_reference_is_a_400_before_persistence(self) -> None:
        """An invalid blank must not become an IntegrityError or AppError."""
        response = self.client.post(
            "/api/purchasing/purchase-orders/",
            {"reference": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reference", str(response.json()["details"]))
        self.assertEqual(AppError.objects.count(), 0)
