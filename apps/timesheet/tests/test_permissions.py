"""Tests for timesheet permission gating."""

from django.test import RequestFactory
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.testing import BaseTestCase


class TimesheetPermissionTests(BaseTestCase):
    """Test that timesheet endpoints require superuser access."""

    def setUp(self):
        self.factory = RequestFactory()
        self.client_api = APIClient()

        self.superuser = Staff.objects.create_user(
            email="super@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_superuser=True,
            is_office_staff=True,
        )
        self.normal_user = Staff.objects.create_user(
            email="normal@example.com",
            password="testpass123",
            first_name="Normal",
            last_name="User",
            is_superuser=False,
            is_office_staff=True,
        )

    def test_weekly_timesheet_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get("/api/timesheets/weekly/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_weekly_timesheet_allowed_for_superuser(self):
        self.client_api.force_authenticate(user=self.superuser)
        response = self.client_api.get("/api/timesheets/weekly/")
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_daily_summary_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get("/api/timesheets/daily/2026-04-01/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_daily_detail_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get(
            f"/api/timesheets/staff/{self.superuser.id}/daily/2026-04-01/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_list_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get("/api/timesheets/staff/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_jobs_list_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get("/api/timesheets/jobs/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_payroll_endpoints_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        # Post week to Xero
        response = self.client_api.post("/api/timesheets/payroll/post-staff-week/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Create pay run
        response = self.client_api.post("/api/timesheets/payroll/pay-runs/create")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Refresh pay runs
        response = self.client_api.post("/api/timesheets/payroll/pay-runs/refresh")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # List pay runs
        response = self.client_api.get("/api/timesheets/payroll/pay-runs/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_stream_payroll_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get(
            "/api/timesheets/payroll/post-staff-week/stream/fake-task-id/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
