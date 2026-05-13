from decimal import Decimal

from django.test import TestCase

from apps.workflow.models import XeroPayItem


class XeroPayItemLookupTests(TestCase):
    def test_get_by_multiplier_prefers_xero_backed_ordinary_time(self):
        stale = XeroPayItem.objects.create(
            name="Time and one half (old)",
            uses_leave_api=False,
            multiplier=Decimal("1.00"),
            xero_id=None,
        )
        ordinary, _ = XeroPayItem.objects.update_or_create(
            name="Ordinary Time",
            uses_leave_api=False,
            defaults={
                "multiplier": Decimal("1.00"),
                "xero_id": "b46b7aa9-055d-4284-845e-ff174c2ae674",
            },
        )

        self.assertEqual(XeroPayItem.get_by_multiplier(Decimal("1.00")), ordinary)
        self.assertNotEqual(XeroPayItem.get_by_multiplier(Decimal("1.00")), stale)

    def test_get_by_multiplier_prefers_xero_backed_time_and_half(self):
        XeroPayItem.objects.update_or_create(
            name="Overtime (1.5)",
            uses_leave_api=False,
            defaults={
                "multiplier": Decimal("1.50"),
                "xero_id": "d618cbbb-44bc-4342-a130-8aa308733490",
            },
        )
        preferred, _ = XeroPayItem.objects.update_or_create(
            name="Time and one half",
            uses_leave_api=False,
            defaults={
                "multiplier": Decimal("1.50"),
                "xero_id": "36b43cff-c725-46f5-a5a6-6861806d4d3a",
            },
        )

        self.assertEqual(XeroPayItem.get_by_multiplier(Decimal("1.50")), preferred)
