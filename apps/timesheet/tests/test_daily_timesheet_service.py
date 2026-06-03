from datetime import date
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
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

    def _create_job(self, *, job_number: int, client_name: str) -> Job:
        client = Client.objects.create(
            name=client_name,
            email=f"{job_number}@example.com",
            xero_last_modified=timezone.now(),
        )
        return Job.objects.create(
            job_number=job_number,
            name=f"Daily Timesheet Job {job_number}",
            charge_out_rate=Decimal("120.00"),
            client=client,
            default_xero_pay_item=self.pay_item,
            staff=self.test_staff,
        )

    def _create_time_line(self, job: Job, *, hours: str, entry_seq: int) -> CostLine:
        return CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="time",
            desc=f"Daily timesheet work {entry_seq}",
            quantity=Decimal(hours),
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
            entry_seq=entry_seq,
        )

    def test_staff_timesheet_data_does_not_lazy_load_job_breakdown_relations(self):
        """Catches N+1 DB access while daily timesheets serialize job/client data."""
        other_job = self._create_job(
            job_number=98767,
            client_name="Second Daily Timesheet Client",
        )
        self._create_time_line(other_job, hours="3.000", entry_seq=2)

        with CaptureQueriesContext(connection) as captured:
            staff_data = DailyTimesheetService._get_staff_timesheet_data(
                self.test_staff, self.target_date
            )

        direct_relation_queries = [
            query["sql"]
            for query in captured
            if 'FROM "job_costset"' in query["sql"]
            or 'FROM "job_job"' in query["sql"]
            or 'FROM "client_client"' in query["sql"]
        ]

        self.assertEqual(direct_relation_queries, [])
        self.assertEqual(
            [(row["client"], row["hours"]) for row in staff_data["job_breakdown"]],
            [
                ("Second Daily Timesheet Client", 3.0),
                ("Daily Timesheet Client", 2.0),
            ],
        )
