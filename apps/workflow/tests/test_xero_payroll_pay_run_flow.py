from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.workflow.api.xero.payroll import create_pay_run, ensure_pay_run_for_week


class EnsurePayRunForWeekTests(SimpleTestCase):
    @patch("apps.workflow.api.xero.payroll.XeroPayRun.objects.filter")
    @patch("apps.workflow.api.xero.payroll.create_pay_run")
    def test_reuses_existing_matching_pay_run(
        self,
        mock_create_pay_run,
        mock_filter,
    ):
        mock_filter.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(
                xero_id="payrun-1",
                payroll_calendar_id="calendar-1",
                period_start_date=date(2026, 5, 4),
                period_end_date=date(2026, 5, 10),
                payment_date=date(2026, 5, 13),
                pay_run_status="Draft",
                pay_run_type="Scheduled",
            )
        )

        result = ensure_pay_run_for_week(date(2026, 5, 4))

        self.assertEqual(result["pay_run_id"], "payrun-1")
        mock_create_pay_run.assert_not_called()

    @patch("apps.workflow.api.xero.payroll.XeroPayRun.objects.filter")
    @patch("apps.workflow.api.xero.payroll.get_pay_run")
    @patch("apps.workflow.api.xero.payroll.create_pay_run")
    @patch("apps.workflow.api.xero.payroll.transform_pay_run")
    def test_creates_and_syncs_missing_pay_run(
        self,
        mock_transform_pay_run,
        mock_create_pay_run,
        mock_get_pay_run,
        mock_filter,
    ):
        mock_filter.return_value.order_by.return_value.first.return_value = None
        mock_create_pay_run.return_value = {
            "pay_run_id": "payrun-2",
            "payroll_calendar_id": "calendar-2",
        }
        xero_pay_run = SimpleNamespace()
        mock_get_pay_run.return_value = xero_pay_run
        local_pay_run = SimpleNamespace(
            id="local-1",
            period_start_date=date(2026, 5, 4),
            period_end_date=date(2026, 5, 10),
            payment_date=date(2026, 5, 13),
            pay_run_status="Draft",
            pay_run_type="Scheduled",
        )
        mock_transform_pay_run.return_value = (local_pay_run, "created")

        result = ensure_pay_run_for_week(date(2026, 5, 4))

        self.assertEqual(result["pay_run_id"], "payrun-2")
        self.assertEqual(result["payroll_calendar_id"], "calendar-2")
        self.assertEqual(result["pay_run_status"], "Draft")
        mock_get_pay_run.assert_called_once_with("payrun-2")
        mock_transform_pay_run.assert_called_once_with(xero_pay_run, "payrun-2")


class CreatePayRunTests(SimpleTestCase):
    @patch("apps.workflow.api.xero.payroll.get_payroll_calendars")
    @patch("apps.workflow.api.xero.payroll.get_tenant_id")
    @patch("apps.workflow.api.xero.payroll.CompanyDefaults")
    @patch("apps.workflow.api.xero.payroll.PayrollNzApi")
    def test_rejects_when_xero_creates_different_period(
        self,
        mock_payroll_api_cls,
        mock_company_defaults,
        mock_get_tenant_id,
        mock_get_payroll_calendars,
    ):
        mock_get_tenant_id.return_value = "tenant-1"
        mock_company_defaults.get_solo.return_value = SimpleNamespace(
            xero_payroll_calendar_name="Weekly Testing"
        )
        mock_get_payroll_calendars.return_value = [
            {"id": "calendar-1", "name": "Weekly Testing"}
        ]
        mock_payroll_api = mock_payroll_api_cls.return_value
        mock_payroll_api.create_pay_run.return_value = SimpleNamespace(
            pay_run=SimpleNamespace(
                pay_run_id="payrun-3",
                period_start_date=date(2026, 4, 14),
                period_end_date=date(2026, 4, 20),
            )
        )

        with self.assertRaisesMessage(
            ValueError,
            "Docketworks currently requires the Xero payroll calendar period to match the selected week exactly.",
        ):
            create_pay_run(date(2026, 5, 4))
