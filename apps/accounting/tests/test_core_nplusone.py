from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.services.core import KPIService, StaffPerformanceService
from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import CostLine, Job, LabourSubtype
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


class AccountingCoreQueryTests(BaseTestCase):
    """Accounting reports must not query job/client data once per row.

    The reports loop over CostLine rows and grouped staff metrics. These tests
    catch refactors that drop the preloaded job/client data by using multiple
    rows and a fixed query budget for the report boundary.
    """

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
        job = Job.objects.create(
            job_number=job_number,
            name=f"Accounting Job {job_number}",
            client=self.client,
            default_xero_pay_item=self.pay_item,
            staff=self.test_staff,
        )
        job.labour_rates.update(charge_out_rate=Decimal("120.00"))
        return job

    def _create_time_line(self, job: Job, staff: Staff, hours: str = "2.000"):
        return CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="time",
            labour_subtype=LabourSubtype.objects.get(name="Workshop"),
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
        """Job breakdown must not fetch each job's client inside the loop.

        This catches removing ``select_related("cost_set__job__client")`` by
        asserting the report stays at fixed query overhead plus one query per
        CostLine kind, even when it emits client names.
        """
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

        with self.assertNumQueries(5):
            breakdown = KPIService.get_job_breakdown_for_date(self.target_date)

        self.assertEqual(breakdown[0]["client_name"], "Accounting Nplusone Client")

    def test_staff_performance_groups_prefetched_cost_lines_by_staff(self):
        """Staff performance must group prefetched lines without per-staff queries.

        This catches metric code that looks up CostLine/job/client data inside
        the staff loop by asserting two staff with separate jobs stay within a
        fixed query ceiling.
        """
        first_staff = self._create_staff("first-performance@example.com")
        second_staff = self._create_staff("second-performance@example.com")
        first_job = self._create_job(98802)
        second_job = self._create_job(98803)
        self._create_time_line(first_job, first_staff)
        self._create_time_line(second_job, second_staff)

        with CaptureQueriesContext(connection) as captured:
            performance = StaffPerformanceService.get_staff_performance_data(
                self.target_date,
                self.target_date,
            )

        self.assertLessEqual(len(captured), 4)
        self.assertEqual(performance["period_summary"]["total_staff"], 2)
