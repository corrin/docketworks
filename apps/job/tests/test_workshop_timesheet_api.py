from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import CostLine, Job
from apps.testing import BaseAPITestCase


class WorkshopTimesheetAPITests(BaseAPITestCase):
    """Verify that normal (non-admin) staff can use the workshop timesheet API."""

    def setUp(self) -> None:
        self.test_client = Client.objects.create(
            name="Workshop Test Client",
            email="workshop-test@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job.objects.create(
            job_number=9000,
            name="Workshop Timesheet Test Job",
            charge_out_rate=Decimal("120.00"),
            client=self.test_client,
        )
        self.staff = Staff.objects.create_user(
            email="workshop-user@example.com",
            password="testpassword123",
            first_name="Workshop",
            last_name="User",
        )
        self.other_staff = Staff.objects.create_user(
            email="other-user@example.com",
            password="testpassword123",
            first_name="Other",
            last_name="User",
        )
        self.url = reverse("jobs:api_workshop_timesheets")
        self.today = date.today().isoformat()

    def _create_entry(self, staff: Staff | None = None) -> dict:
        """Helper: create an entry as the given staff and return the response data."""
        staff = staff or self.staff
        self.client.force_authenticate(user=staff)
        resp = self.client.post(
            self.url,
            {
                "job_id": str(self.job.id),
                "accounting_date": self.today,
                "hours": "1.00",
                "description": "Test entry",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def test_normal_user_can_create_entry(self) -> None:
        self.client.force_authenticate(user=self.staff)
        resp = self.client.post(
            self.url,
            {
                "job_id": str(self.job.id),
                "accounting_date": self.today,
                "hours": "2.00",
                "description": "Workshop task",
                "is_billable": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["job_number"], self.job.job_number)

    def test_normal_user_can_list_entries(self) -> None:
        self._create_entry()
        self.client.force_authenticate(user=self.staff)
        resp = self.client.get(self.url, {"date": self.today})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["entries"]), 1)

    def test_normal_user_can_update_own_entry(self) -> None:
        entry = self._create_entry()
        self.client.force_authenticate(user=self.staff)
        resp = self.client.patch(
            self.url,
            {
                "entry_id": entry["id"],
                "description": "Updated description",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["description"], "Updated description")

    def test_normal_user_can_delete_own_entry(self) -> None:
        entry = self._create_entry()
        self.client.force_authenticate(user=self.staff)
        resp = self.client.delete(
            f"{self.url}?entry_id={entry['id']}",
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(CostLine.objects.filter(id=entry["id"]).exists())

    def test_unauthenticated_rejected(self) -> None:
        self.client.force_authenticate(user=None)
        resp = self.client.get(self.url)
        self.assertIn(resp.status_code, (401, 403))

    def test_cannot_update_other_staff_entry(self) -> None:
        entry = self._create_entry(staff=self.other_staff)
        self.client.force_authenticate(user=self.staff)
        resp = self.client.patch(
            self.url,
            {
                "entry_id": entry["id"],
                "description": "Hijacked",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
