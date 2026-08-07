"""API regression tests for the staff-performance report."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.testing import BaseAPITestCase


class StaffPerformanceAPITests(BaseAPITestCase):
    """The report must serve its declared contract when no hours exist."""

    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.test_staff)
        self.url = reverse("accounting:api_staff_performance_summary")

    def test_empty_period_returns_complete_zeroed_summary(self) -> None:
        response = self.client.get(
            self.url,
            data={"start_date": "2026-06-06", "end_date": "2026-06-07"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(
            response.json(),
            {
                "team_averages": {
                    "billable_percentage": 0.0,
                    "revenue_per_hour": 0.0,
                    "profit_per_hour": 0.0,
                    "jobs_per_person": 0.0,
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "total_revenue": 0.0,
                    "total_profit": 0.0,
                },
                "staff": [],
                "period_summary": {
                    "start_date": "2026-06-06",
                    "end_date": "2026-06-07",
                    "total_staff": 0,
                    "period_description": "June 06 - June 07, 2026",
                },
            },
        )
