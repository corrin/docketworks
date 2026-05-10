import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults, XeroPayRun


class PayRunListApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client_api = APIClient()
        self.superuser = Staff.objects.create_user(
            email="payruns@example.com",
            password="testpass123",
            first_name="Pay",
            last_name="Runs",
            is_superuser=True,
            is_office_staff=True,
        )
        self.client_api.force_authenticate(user=self.superuser)

        company = CompanyDefaults.get_solo()
        company.xero_payroll_calendar_id = uuid.uuid4()
        company.save(update_fields=["xero_payroll_calendar_id"])
        self.calendar_id = company.xero_payroll_calendar_id

    @patch("apps.timesheet.views.api.build_xero_payroll_url")
    def test_list_pay_runs_uses_local_mirror_table(self, mock_build_xero_payroll_url):
        mock_build_xero_payroll_url.return_value = "https://example.test/payrun/1"
        pay_run = XeroPayRun.objects.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id="tenant-1",
            payroll_calendar_id=self.calendar_id,
            period_start_date=date(2026, 5, 5),
            period_end_date=date(2026, 5, 11),
            payment_date=date(2026, 5, 13),
            pay_run_status="Draft",
            raw_json={},
            xero_last_modified=datetime(2026, 5, 13, tzinfo=timezone.utc),
        )

        response = self.client_api.get(reverse("timesheet:api_list_pay_runs"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["pay_runs"]), 1)
        self.assertEqual(payload["pay_runs"][0]["xero_id"], str(pay_run.xero_id))
        self.assertEqual(payload["pay_runs"][0]["pay_run_status"], "Draft")
