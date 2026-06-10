from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job, LabourSubtype
from apps.job.serializers.costing_serializer import CostLineCreateUpdateSerializer
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


class CostLineTimeRateSerializationTests(BaseTestCase):
    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Rate Serialization Client",
            email="rates@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job.objects.create(
            job_number=9100,
            name="Rate Serialization Job",
            client=self.client_obj,
            staff=self.test_staff,
        )
        self.job.labour_rates.update(charge_out_rate=Decimal("125.00"))
        self.staff = Staff.objects.create_user(
            email="rate-serializer@example.com",
            password="testpassword123",
            first_name="Rate",
            last_name="Serializer",
            base_wage_rate=Decimal("50.00"),
            is_office_staff=True,
        )
        self.ordinary_pay_item = XeroPayItem.get_by_multiplier(Decimal("1.00"))
        self.overtime_pay_item = XeroPayItem.get_by_multiplier(Decimal("1.50"))

    def test_create_calculates_pay_and_bill_multipliers_independently(self) -> None:
        serializer = CostLineCreateUpdateSerializer(
            data={
                "kind": "time",
                "desc": "Office overtime",
                "quantity": "2.000",
                "unit_cost": "0.00",
                "unit_rev": "0.00",
                "accounting_date": date.today(),
                "meta": {
                    "staff_id": str(self.staff.id),
                    "date": date.today().isoformat(),
                    "created_from_timesheet": True,
                    "wage_rate_multiplier": 1.5,
                    "bill_rate_multiplier": 1.0,
                },
                "ext_refs": {},
            },
            context={"staff": self.staff},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        line = serializer.save(cost_set=self.job.latest_actual)

        self.assertEqual(line.unit_cost, Decimal("90.00"))
        self.assertEqual(line.unit_rev, Decimal("125.00"))
        self.assertEqual(line.xero_pay_item, self.overtime_pay_item)
        self.assertEqual(
            line.xero_pay_item.multiplier,
            Decimal(str(line.meta["wage_rate_multiplier"])).quantize(Decimal("0.01")),
        )
        self.assertEqual(line.meta["is_billable"], True)

    def test_update_pay_multiplier_updates_xero_pay_item(self) -> None:
        line = self.job.latest_actual.cost_lines.create(
            kind="time",
            labour_subtype=LabourSubtype.objects.get(name="Workshop"),
            desc="Ordinary row",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("50.00"),
            unit_rev=Decimal("125.00"),
            accounting_date=date.today(),
            xero_pay_item=self.ordinary_pay_item,
            ext_refs={},
            meta={
                "staff_id": str(self.staff.id),
                "date": date.today().isoformat(),
                "created_from_timesheet": True,
                "wage_rate_multiplier": 1.0,
                "is_billable": True,
            },
        )
        serializer = CostLineCreateUpdateSerializer(
            line,
            data={
                "meta": {
                    **line.meta,
                    "wage_rate_multiplier": 1.5,
                    "bill_rate_multiplier": 1.0,
                },
            },
            partial=True,
            context={"staff": self.staff},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        updated = serializer.save()

        self.assertEqual(updated.unit_cost, Decimal("90.00"))
        self.assertEqual(updated.unit_rev, Decimal("125.00"))
        self.assertEqual(updated.xero_pay_item, self.overtime_pay_item)
        self.assertEqual(
            updated.xero_pay_item.multiplier,
            Decimal(str(updated.meta["wage_rate_multiplier"])).quantize(
                Decimal("0.01")
            ),
        )

    def test_leave_job_keeps_leave_pay_item(self) -> None:
        sick_pay_item = XeroPayItem.objects.get(
            name="Sick Leave",
            uses_leave_api=True,
        )
        if not sick_pay_item.xero_id:
            sick_pay_item.xero_id = "b91d0ab1-5422-43c4-b4fa-6e3e5af03871"
            sick_pay_item.save(update_fields=["xero_id"])
        sick_job = Job.objects.create(
            job_number=9101,
            name="Sick Leave",
            client=self.client_obj,
            staff=self.test_staff,
            default_xero_pay_item=sick_pay_item,
        )
        sick_job.labour_rates.update(charge_out_rate=Decimal("0.00"))
        serializer = CostLineCreateUpdateSerializer(
            data={
                "kind": "time",
                "desc": "Sick leave",
                "quantity": "8.000",
                "unit_cost": "0.00",
                "unit_rev": "0.00",
                "accounting_date": date.today(),
                "meta": {
                    "staff_id": str(self.staff.id),
                    "date": date.today().isoformat(),
                    "created_from_timesheet": True,
                    "wage_rate_multiplier": 1.0,
                    "bill_rate_multiplier": 1.0,
                    "is_billable": True,
                },
                "ext_refs": {},
            },
            context={"staff": self.staff},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        line = serializer.save(cost_set=sick_job.latest_actual)

        self.assertEqual(line.xero_pay_item, sick_pay_item)
        self.assertEqual(line.unit_rev, Decimal("0.00"))
        self.assertEqual(line.meta["bill_rate_multiplier"], 0.0)
        self.assertEqual(line.meta["is_billable"], False)
