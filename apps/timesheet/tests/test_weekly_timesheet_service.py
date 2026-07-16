from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import CostLine, Job, LabourSubtype
from apps.testing import BaseTestCase
from apps.timesheet.services.weekly_timesheet_service import WeeklyTimesheetService
from apps.workflow.models import CompanyDefaults, XeroPayItem


class WeeklyTimesheetServiceCostTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        company = CompanyDefaults.get_solo()
        company.annual_leave_loading = Decimal("20.00")
        company.weekend_timesheets_enabled = False
        company.save(
            update_fields=["annual_leave_loading", "weekend_timesheets_enabled"]
        )

        self.staff = Staff.objects.create_user(
            email="daniel-cost-test@example.com",
            password="testpass123",
            first_name="Daniel",
            last_name="Patel",
            base_wage_rate=Decimal("38.00"),
            xero_user_id="bca2d20d-f8ac-4c3a-a866-a90a2cffaa13",
        )
        Staff.objects.filter(pk=self.staff.pk).update(
            date_joined=timezone.make_aware(datetime(2025, 1, 1))
        )
        self.company = Company.objects.create(
            name="Cost Test Company",
            email="cost-test@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.pay_item = XeroPayItem.get_ordinary_time()
        self.job = Job.objects.create(
            job_number=98765,
            name="Weekly Cost Test",
            company=self.company,
            default_xero_pay_item=self.pay_item,
            staff=self.test_staff,
        )
        self.job.labour_rates.update(charge_out_rate=Decimal("120.00"))

    def test_weekly_cash_and_loaded_costs_use_annual_leave_loading(self):
        week_start = date(2025, 5, 5)
        for day_offset in range(5):
            CostLine.objects.create(
                cost_set=self.job.latest_actual,
                kind="time",
                labour_subtype=LabourSubtype.objects.get(name="Workshop"),
                desc="Ordinary time",
                quantity=Decimal("8.000"),
                unit_cost=Decimal("38.00"),
                unit_rev=Decimal("0.00"),
                accounting_date=date(2025, 5, 5 + day_offset),
                meta={
                    "staff_id": str(self.staff.id),
                    "is_billable": False,
                    "wage_rate_multiplier": 1.0,
                },
                ext_refs={},
                xero_pay_item=self.pay_item,
            )

        overview = WeeklyTimesheetService.get_weekly_overview(week_start)
        [staff_row] = overview["staff_data"]

        self.assertEqual(staff_row["weekly_base_cost"], 1520.00)
        self.assertEqual(staff_row["weekly_cost"], 1824.00)
