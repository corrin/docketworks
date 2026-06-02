from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.utils import timezone

from apps.accounting.services.core import KPIService, StaffPerformanceService
from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import CostLine, Job
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults, XeroPayItem


class AccountingCoreQueryTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.target_date = date(2026, 5, 22)
        self.client = Client.objects.create(
            name="Accounting Nplusone Client",
            email="accounting-nplusone@example.com",
            xero_last_modified=timezone.now(),
        )
        self.pay_item = XeroPayItem.get_ordinary_time()

    def _create_staff(self, email: str) -> Staff:
        return Staff.objects.create_user(
            email=email,
            password="testpass",
            first_name="Query",
            last_name="Staff",
            is_workshop_staff=True,
            date_joined=timezone.make_aware(timezone.datetime(2026, 5, 1, 8, 0, 0)),
            xero_user_id=str(uuid4()),
        )

    def _create_job(self, job_number: int) -> Job:
        return Job.objects.create(
            job_number=job_number,
            name=f"Accounting Job {job_number}",
            charge_out_rate=Decimal("120.00"),
            client=self.client,
            default_xero_pay_item=self.pay_item,
            staff=self.test_staff,
        )

    def _create_time_line(self, job: Job, staff: Staff, hours: str = "2.000"):
        return CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="time",
            desc="Accounting time",
            quantity=Decimal(hours),
            unit_cost=Decimal("40.00"),
            unit_rev=Decimal("120.00"),
            accounting_date=self.target_date,
            meta={
                "staff_id": str(staff.id),
                "is_billable": True,
                "wage_rate_multiplier": 1.0,
            },
            ext_refs={},
            xero_pay_item=self.pay_item,
            staff=staff,
            entry_seq=1,
        )

    def test_kpi_job_breakdown_preloads_job_client(self):
        job = self._create_job(98801)
        CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="material",
            desc="Accounting material",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("40.00"),
            unit_rev=Decimal("120.00"),
            accounting_date=self.target_date,
            meta={},
            ext_refs={},
        )

        with self.assertNumQueries(4):
            breakdown = KPIService.get_job_breakdown_for_date(self.target_date)

        self.assertEqual(breakdown[0]["client_name"], "Accounting Nplusone Client")

    def test_staff_performance_groups_prefetched_cost_lines_by_staff(self):
        first_staff = self._create_staff("first-performance@example.com")
        second_staff = self._create_staff("second-performance@example.com")
        first_job = self._create_job(98802)
        second_job = self._create_job(98803)
        self._create_time_line(first_job, first_staff)
        self._create_time_line(second_job, second_staff)

        CompanyDefaults.get_solo()
        with self.assertNumQueries(3):
            performance = StaffPerformanceService.get_staff_performance_data(
                self.target_date,
                self.target_date,
            )

        self.assertEqual(performance["period_summary"]["total_staff"], 2)
