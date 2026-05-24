from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.client.models import Client
from apps.job.models import CostLine, Job
from apps.testing import BaseTestCase
from apps.timesheet.services.daily_timesheet_service import DailyTimesheetService
from apps.workflow.models import XeroPayItem


class DailyTimesheetServiceTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.target_date = date(2026, 5, 22)
        self.client = Client.objects.create(
            name="Daily Timesheet Client",
            email="daily-timesheet@example.com",
            xero_last_modified=timezone.now(),
        )
        self.pay_item = XeroPayItem.get_ordinary_time()
        self.job = Job.objects.create(
            job_number=98766,
            name="Daily Timesheet Job",
            charge_out_rate=Decimal("120.00"),
            client=self.client,
            default_xero_pay_item=self.pay_item,
            staff=self.test_staff,
        )
        self.cost_line = CostLine.objects.create(
            cost_set=self.job.latest_actual,
            kind="time",
            desc="Daily timesheet work",
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

    def test_job_breakdown_uses_preloaded_job_client(self):
        cost_lines = CostLine.objects.filter(pk=self.cost_line.pk).select_related(
            "cost_set__job__client"
        )

        with self.assertNumQueries(1):
            breakdown = DailyTimesheetService._get_job_breakdown(cost_lines)

        self.assertEqual(breakdown[0]["client"], "Daily Timesheet Client")
