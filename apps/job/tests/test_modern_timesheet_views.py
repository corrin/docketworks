from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.client.models import Client
from apps.job.models import CostLine, Job
from apps.job.serializers.costing_serializer import TimesheetCostLineSerializer
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


class ModernTimesheetEntryQueryTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.target_date = date(2026, 5, 22)
        self.client = Client.objects.create(
            name="Modern Timesheet Client",
            email="modern-timesheet@example.com",
            xero_last_modified=timezone.now(),
        )
        self.pay_item = XeroPayItem.get_ordinary_time()
        self.job = Job.objects.create(
            job_number=98767,
            name="Modern Timesheet Job",
            charge_out_rate=Decimal("120.00"),
            client=self.client,
            default_xero_pay_item=self.pay_item,
            staff=self.test_staff,
        )
        self.test_staff.wage_rate = Decimal("40.00")
        self.test_staff.save(update_fields=["wage_rate"])
        self.cost_line = CostLine.objects.create(
            cost_set=self.job.latest_actual,
            kind="time",
            desc="Modern timesheet work",
            quantity=Decimal("2.000"),
            unit_cost=Decimal("40.00"),
            unit_rev=Decimal("120.00"),
            accounting_date=self.target_date,
            meta={
                "staff_id": str(self.test_staff.id),
                "is_billable": True,
                "wage_rate_multiplier": 1.0,
            },
            ext_refs={},
            xero_pay_item=self.pay_item,
            staff=self.test_staff,
            entry_seq=1,
        )

    def test_timesheet_cost_line_serializer_uses_preloaded_relations(self):
        cost_lines = (
            CostLine.objects.filter(pk=self.cost_line.pk)
            .select_related("cost_set__job__client", "staff", "xero_pay_item")
            .order_by("entry_seq")
        )

        with self.assertNumQueries(1):
            data = TimesheetCostLineSerializer(cost_lines, many=True).data

        self.assertEqual(data[0]["client_name"], "Modern Timesheet Client")
        self.assertEqual(data[0]["wage_rate"], 40.0)
        self.assertEqual(data[0]["xero_pay_item_name"], self.pay_item.name)
