from datetime import date
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import CostLine, Job, LabourSubtype
from apps.job.serializers.costing_serializer import TimesheetCostLineSerializer
from apps.job.views.modern_timesheet_views import ModernTimesheetEntryView
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
            client=self.client,
            default_xero_pay_item=self.pay_item,
            staff=self.test_staff,
        )
        self.job.labour_rates.update(charge_out_rate=Decimal("120.00"))
        self.test_staff.wage_rate = Decimal("40.00")
        self.test_staff.save(update_fields=["wage_rate"])
        self.cost_line = CostLine.objects.create(
            cost_set=self.job.latest_actual,
            kind="time",
            labour_subtype=LabourSubtype.objects.get(name="Workshop"),
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
            .select_related(
                "cost_set__job__client",
                "staff",
                "xero_pay_item",
                "labour_subtype",
            )
            .prefetch_related("cost_set__job__labour_rates")
            .order_by("entry_seq")
        )

        # 1 main query + 1 labour_rates prefetch
        with self.assertNumQueries(2):
            data = TimesheetCostLineSerializer(cost_lines, many=True).data

        self.assertEqual(data[0]["client_name"], "Modern Timesheet Client")
        self.assertEqual(data[0]["wage_rate"], 40.0)
        self.assertEqual(data[0]["xero_pay_item_name"], self.pay_item.name)
        self.assertEqual(data[0]["labour_subtype_name"], "Workshop")
        self.assertEqual(data[0]["charge_out_rate"], 120.0)

    def test_timesheet_entries_api_returns_numeric_charge_out_rate(self) -> None:
        superuser = Staff.objects.create_user(
            email="modern-timesheet-api@example.com",
            password="x",
            first_name="Modern",
            last_name="API",
            is_superuser=True,
            is_office_staff=True,
        )
        request = APIRequestFactory().get(
            "/api/job/timesheet/entries/",
            {
                "staff_id": str(self.test_staff.id),
                "date": self.target_date.isoformat(),
            },
        )
        force_authenticate(request, user=superuser)

        response = ModernTimesheetEntryView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["cost_lines"][0]["charge_out_rate"], 120.0)
        self.assertIsInstance(response.data["cost_lines"][0]["charge_out_rate"], float)
