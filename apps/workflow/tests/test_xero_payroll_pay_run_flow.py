from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.workflow.api.xero.payroll import create_pay_run, ensure_pay_run_for_week

WEEK = date(2026, 5, 4)  # a Monday
OTHER_WEEK = date(2026, 4, 27)  # also a Monday


def _draft(week_start, xero_id="payrun-1", calendar_id="cal-1"):
    return SimpleNamespace(
        xero_id=xero_id,
        payroll_calendar_id=calendar_id,
        period_start_date=week_start,
        period_end_date=week_start + timedelta(days=6),
        payment_date=week_start + timedelta(days=9),
        pay_run_status="Draft",
        pay_run_type="Scheduled",
    )


@patch("apps.workflow.api.xero.payroll.CompanyDefaults")
@patch("apps.workflow.api.xero.payroll.XeroPayRun")
class EnsurePayRunForWeekTests(SimpleTestCase):
    @patch("apps.workflow.api.xero.payroll.create_pay_run")
    def test_reuses_open_draft_for_the_requested_week(
        self, mock_create_pay_run, mock_xero_pay_run, mock_company_defaults
    ):
        mock_company_defaults.get_solo.return_value.xero_payroll_calendar_id = "cal-1"
        mock_xero_pay_run.objects.filter.return_value = [_draft(WEEK)]

        result = ensure_pay_run_for_week(WEEK)

        self.assertEqual(result["pay_run_id"], "payrun-1")
        mock_create_pay_run.assert_not_called()

    @patch("apps.workflow.api.xero.payroll.transform_pay_run")
    @patch("apps.workflow.api.xero.payroll.get_pay_run")
    @patch("apps.workflow.api.xero.payroll.create_pay_run")
    def test_creates_and_mirrors_pay_run_when_no_draft_open(
        self,
        mock_create_pay_run,
        mock_get_pay_run,
        mock_transform_pay_run,
        mock_xero_pay_run,
        mock_company_defaults,
    ):
        mock_company_defaults.get_solo.return_value.xero_payroll_calendar_id = "cal-1"
        mock_xero_pay_run.objects.filter.return_value = []
        mock_create_pay_run.return_value = {
            "pay_run_id": "payrun-2",
            "payroll_calendar_id": "cal-2",
        }
        xero_pay_run_obj = SimpleNamespace()
        mock_get_pay_run.return_value = xero_pay_run_obj
        mock_transform_pay_run.return_value = (
            SimpleNamespace(
                id="local-1",
                period_start_date=WEEK,
                period_end_date=WEEK + timedelta(days=6),
                payment_date=WEEK + timedelta(days=9),
                pay_run_status="Draft",
                pay_run_type="Scheduled",
            ),
            "created",
        )

        result = ensure_pay_run_for_week(WEEK)

        self.assertEqual(result["pay_run_id"], "payrun-2")
        self.assertEqual(result["payroll_calendar_id"], "cal-2")
        mock_create_pay_run.assert_called_once_with(WEEK)
        mock_get_pay_run.assert_called_once_with("payrun-2")
        mock_transform_pay_run.assert_called_once_with(xero_pay_run_obj, "payrun-2")

    @patch("apps.workflow.api.xero.payroll.create_pay_run")
    def test_raises_when_a_draft_for_a_different_week_is_open(
        self, mock_create_pay_run, mock_xero_pay_run, mock_company_defaults
    ):
        mock_company_defaults.get_solo.return_value.xero_payroll_calendar_id = "cal-1"
        mock_xero_pay_run.objects.filter.return_value = [_draft(OTHER_WEEK)]

        with self.assertRaisesRegex(ValueError, "only one draft pay run per calendar"):
            ensure_pay_run_for_week(WEEK)
        mock_create_pay_run.assert_not_called()

    def test_raises_when_calendar_not_configured(
        self, mock_xero_pay_run, mock_company_defaults
    ):
        mock_company_defaults.get_solo.return_value.xero_payroll_calendar_id = None

        with self.assertRaisesRegex(ValueError, "xero_payroll_calendar_id"):
            ensure_pay_run_for_week(WEEK)


class CreatePayRunTests(SimpleTestCase):
    @patch("apps.workflow.api.xero.payroll.transform_pay_run")
    @patch("apps.workflow.api.xero.payroll.get_payroll_calendars")
    @patch("apps.workflow.api.xero.payroll.get_tenant_id")
    @patch("apps.workflow.api.xero.payroll.CompanyDefaults")
    @patch("apps.workflow.api.xero.payroll.PayrollNzApi")
    def test_mirrors_pay_run_then_raises_when_xero_creates_a_different_period(
        self,
        mock_payroll_api_cls,
        mock_company_defaults,
        mock_get_tenant_id,
        mock_get_payroll_calendars,
        mock_transform_pay_run,
    ):
        mock_get_tenant_id.return_value = "tenant-1"
        mock_company_defaults.get_solo.return_value = SimpleNamespace(
            xero_payroll_calendar_name="Weekly Testing"
        )
        mock_get_payroll_calendars.return_value = [
            {"id": "calendar-1", "name": "Weekly Testing"}
        ]
        created = SimpleNamespace(
            pay_run_id="payrun-3",
            period_start_date=date(2026, 4, 14),
            period_end_date=date(2026, 4, 20),
        )
        mock_payroll_api_cls.return_value.create_pay_run.return_value = SimpleNamespace(
            pay_run=created
        )

        with self.assertRaisesRegex(
            ValueError,
            "Docketworks currently requires the Xero payroll calendar period to match",
        ):
            create_pay_run(date(2026, 5, 4))

        mock_transform_pay_run.assert_called_once_with(created, "payrun-3")
