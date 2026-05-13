import uuid
from datetime import date, datetime
from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults


class PayrollPostStartApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client_api = APIClient()
        self.superuser = Staff.objects.create_user(
            email="payroll-post@example.com",
            password="testpass123",
            first_name="Payroll",
            last_name="Poster",
            is_superuser=True,
            is_office_staff=True,
        )
        self.client_api.force_authenticate(user=self.superuser)

    @patch("apps.timesheet.views.api.uuid_module.uuid4")
    def test_post_staff_week_returns_task_id_and_stream_url(self, mock_uuid4):
        task_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        mock_uuid4.return_value = task_id
        response = self.client_api.post(
            reverse("timesheet:api_post_staff_week"),
            {
                "staff_ids": [str(self.superuser.id)],
                "week_start_date": "2026-05-04",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["task_id"], str(task_id))
        self.assertEqual(
            payload["stream_url"],
            f"/api/timesheets/payroll/post-staff-week/stream/{task_id}/",
        )
        self.assertEqual(
            cache.get(f"payroll_task_{task_id}"),
            {
                "staff_ids": [str(self.superuser.id)],
                "week_start_date": "2026-05-04",
                "status": "pending",
            },
        )

    @patch("apps.timesheet.views.api.post_staff_week_to_xero")
    @patch("apps.timesheet.views.api.get_all_timesheets_for_week")
    @patch("apps.timesheet.views.api.ensure_pay_run_for_week")
    @patch("apps.timesheet.views.api.validate_pay_items_for_week")
    def test_stream_aborts_before_employee_posts_when_ensure_pay_run_fails(
        self,
        mock_validate_pay_items,
        mock_ensure_pay_run,
        mock_get_all_timesheets,
        mock_post_staff_week,
    ):
        task_id = "22222222-2222-2222-2222-222222222222"
        cache.set(
            f"payroll_task_{task_id}",
            {
                "staff_ids": [str(self.superuser.id)],
                "week_start_date": "2026-05-04",
                "status": "pending",
            },
        )
        mock_ensure_pay_run.side_effect = ValueError("pay run week is invalid in Xero")

        response = self.client_api.get(
            reverse("timesheet:api_post_staff_week_stream", args=[task_id])
        )
        payload = b"".join(response.streaming_content).decode()

        self.assertIn('"event": "error"', payload)
        self.assertIn("pay run week is invalid in Xero", payload)
        self.assertIn('"failed": 1', payload)
        mock_validate_pay_items.assert_called_once()
        mock_ensure_pay_run.assert_called_once()
        mock_get_all_timesheets.assert_not_called()
        mock_post_staff_week.assert_not_called()

    @patch("apps.timesheet.views.api.post_staff_week_to_xero")
    @patch("apps.timesheet.views.api.get_all_timesheets_for_week")
    @patch("apps.timesheet.views.api.ensure_pay_run_for_week")
    @patch("apps.timesheet.views.api.validate_pay_items_for_week")
    def test_stream_ensures_pay_run_before_fetching_timesheets(
        self,
        mock_validate_pay_items,
        mock_ensure_pay_run,
        mock_get_all_timesheets,
        mock_post_staff_week,
    ):
        task_id = "33333333-3333-3333-3333-333333333333"
        cache.set(
            f"payroll_task_{task_id}",
            {
                "staff_ids": [str(self.superuser.id)],
                "week_start_date": "2026-05-04",
                "status": "pending",
            },
        )
        call_order: list[str] = []

        def record_validate(*args, **kwargs):
            call_order.append("validate")

        def record_ensure(*args, **kwargs):
            call_order.append("ensure")

        def record_fetch(*args, **kwargs):
            call_order.append("fetch_timesheets")
            return {}

        def record_post(*args, **kwargs):
            call_order.append("post_staff")
            return {"success": True, "work_hours": "8"}

        mock_validate_pay_items.side_effect = record_validate
        mock_ensure_pay_run.side_effect = record_ensure
        mock_get_all_timesheets.side_effect = record_fetch
        mock_post_staff_week.side_effect = record_post

        response = self.client_api.get(
            reverse("timesheet:api_post_staff_week_stream", args=[task_id])
        )
        payload = b"".join(response.streaming_content).decode()

        self.assertIn('"event": "done"', payload)
        self.assertEqual(
            call_order,
            ["validate", "ensure", "fetch_timesheets", "post_staff"],
        )

    @patch("apps.timesheet.views.api.post_staff_week_to_xero")
    @patch("apps.timesheet.views.api.get_all_timesheets_for_week")
    @patch("apps.timesheet.views.api.ensure_pay_run_for_week")
    @patch("apps.timesheet.views.api.validate_pay_items_for_week")
    def test_stream_posts_staff_who_left_after_posted_week_started(
        self,
        mock_validate_pay_items,
        mock_ensure_pay_run,
        mock_get_all_timesheets,
        mock_post_staff_week,
    ):
        Staff.objects.filter(pk=self.superuser.pk).update(
            date_joined=timezone.make_aware(datetime(2026, 1, 1)),
            date_left=date(2026, 5, 10),
        )
        task_id = "44444444-4444-4444-4444-444444444444"
        cache.set(
            f"payroll_task_{task_id}",
            {
                "staff_ids": [str(self.superuser.id)],
                "week_start_date": "2026-05-04",
                "status": "pending",
            },
        )
        mock_get_all_timesheets.return_value = {}
        mock_post_staff_week.return_value = {"success": True, "work_hours": "8"}

        response = self.client_api.get(
            reverse("timesheet:api_post_staff_week_stream", args=[task_id])
        )
        payload = b"".join(response.streaming_content).decode()

        self.assertIn('"event": "done"', payload)
        mock_post_staff_week.assert_called_once()
        self.assertNotIn('"skipped": true', payload)

    @patch("apps.timesheet.views.api.post_staff_week_to_xero")
    @patch("apps.timesheet.views.api.get_all_timesheets_for_week")
    @patch("apps.timesheet.views.api.ensure_pay_run_for_week")
    @patch("apps.timesheet.views.api.validate_pay_items_for_week")
    def test_stream_skips_staff_who_left_before_posted_week(
        self,
        mock_validate_pay_items,
        mock_ensure_pay_run,
        mock_get_all_timesheets,
        mock_post_staff_week,
    ):
        Staff.objects.filter(pk=self.superuser.pk).update(
            date_joined=timezone.make_aware(datetime(2026, 1, 1)),
            date_left=date(2026, 5, 3),
        )
        task_id = "55555555-5555-5555-5555-555555555555"
        cache.set(
            f"payroll_task_{task_id}",
            {
                "staff_ids": [str(self.superuser.id)],
                "week_start_date": "2026-05-04",
                "status": "pending",
            },
        )
        mock_get_all_timesheets.return_value = {}

        response = self.client_api.get(
            reverse("timesheet:api_post_staff_week_stream", args=[task_id])
        )
        payload = b"".join(response.streaming_content).decode()

        self.assertIn('"skipped": true', payload)
        mock_post_staff_week.assert_not_called()


class WeeklyTimesheetApiContractTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client_api = APIClient()
        self.superuser = Staff.objects.create_user(
            email="weekly-timesheet@example.com",
            password="testpass123",
            first_name="Weekly",
            last_name="Timesheet",
            is_superuser=True,
            is_office_staff=True,
        )
        self.client_api.force_authenticate(user=self.superuser)

    def test_weekly_api_returns_five_days_when_weekends_disabled(self):
        company = CompanyDefaults.get_solo()
        company.weekend_timesheets_enabled = False
        company.save(update_fields=["weekend_timesheets_enabled"])

        response = self.client_api.get(
            reverse("timesheet:api_weekly_timesheet"),
            {"start_date": "2026-05-04"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["weekend_enabled"], False)
        self.assertEqual(payload["week_type"], "5-day")
        self.assertEqual(payload["week_days"], [f"2026-05-0{i}" for i in range(4, 9)])
        self.assertEqual(payload["start_date"], "2026-05-04")
        self.assertEqual(payload["end_date"], "2026-05-08")

    def test_weekly_api_returns_seven_days_when_weekends_enabled(self):
        company = CompanyDefaults.get_solo()
        company.weekend_timesheets_enabled = True
        company.save(update_fields=["weekend_timesheets_enabled"])

        response = self.client_api.get(
            reverse("timesheet:api_weekly_timesheet"),
            {"start_date": "2026-05-04"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["weekend_enabled"], True)
        self.assertEqual(payload["week_type"], "7-day")
        self.assertEqual(
            payload["week_days"],
            [f"2026-05-0{i}" for i in range(4, 10)] + ["2026-05-10"],
        )
        self.assertEqual(payload["start_date"], "2026-05-04")
        self.assertEqual(payload["end_date"], "2026-05-10")
