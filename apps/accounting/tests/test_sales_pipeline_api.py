"""API-level tests for the Sales Pipeline Report endpoint.

Covers every bullet from the requirements plan
``docs/plans/2026-04-16-sales-pipeline-report.md`` "API tests" section:
shape on valid requests, default-to-today ``end_date``, and each explicit
validation failure mode.
"""

from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.testing import BaseAPITestCase


class SalesPipelineAPITests(BaseAPITestCase):
    """End-to-end request/response tests for
    ``GET /api/accounting/reports/sales-pipeline/``."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.office_staff = Staff.objects.create_user(
            email="sales-pipeline-api@example.test",
            password="testpass",
            first_name="Office",
            last_name="Staff",
            is_office_staff=True,
        )

    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.office_staff)
        self.url = reverse("accounting:api_sales_pipeline")

    def _get(self, params: dict | None = None):
        return self.client.get(self.url, data=params or {})

    def test_valid_request_returns_all_sections(self):
        resp = self._get(
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "rolling_window_weeks": 4,
                "trend_weeks": 4,
            }
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        body = resp.json()
        for key in (
            "period",
            "scoreboard",
            "pipeline_snapshot",
            "velocity",
            "conversion_funnel",
            "trend",
            "warnings",
        ):
            self.assertIn(key, body, f"missing top-level key {key!r}")
        # Trend bucket count matches the explicit ``trend_weeks`` param.
        self.assertEqual(len(body["trend"]["weeks"]), 4)
        self.assertEqual(len(body["trend"]["rolling_average"]), 4)

    def test_omitted_end_date_defaults_to_today(self):
        today = timezone.localdate()
        resp = self._get({"start_date": "2026-01-01"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        body = resp.json()
        self.assertEqual(body["period"]["end_date"], today.isoformat())

    def test_missing_start_date_returns_400(self):
        resp = self._get({"end_date": "2026-02-01"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        body = resp.json()
        self.assertIn("details", body)
        self.assertIn("start_date", body["details"])

    def test_invalid_start_date_returns_400(self):
        resp = self._get({"start_date": "not-a-date"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_date", resp.json()["details"])

    def test_invalid_end_date_returns_400(self):
        resp = self._get({"start_date": "2026-01-01", "end_date": "2026-13-40"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_date", resp.json()["details"])

    def test_start_after_end_returns_400(self):
        resp = self._get({"start_date": "2026-02-10", "end_date": "2026-02-01"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        # ``validate()`` surfaces this on end_date per the serializer.
        self.assertIn("end_date", resp.json()["details"])

    def test_non_positive_rolling_window_returns_400(self):
        resp = self._get(
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "rolling_window_weeks": 0,
            }
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rolling_window_weeks", resp.json()["details"])

    def test_non_positive_trend_weeks_returns_400(self):
        resp = self._get(
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "trend_weeks": 0,
            }
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("trend_weeks", resp.json()["details"])

    def test_unexpected_service_failure_returns_standard_error_shape(self):
        """Unhandled service exceptions must be persisted via
        ``persist_app_error`` and surfaced as a 500 with the standard error
        payload (``error`` plus ``details.error_id``)."""
        with patch(
            "apps.accounting.views.sales_pipeline_view.SalesPipelineService.get_report",
            side_effect=RuntimeError("boom"),
        ):
            resp = self._get({"start_date": "2026-01-01", "end_date": "2026-01-31"})
        self.assertEqual(
            resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR, resp.content
        )
        body = resp.json()
        self.assertIn("error", body)
        self.assertIn("details", body)
        self.assertIn("error_id", body["details"])

    def test_unauthenticated_request_is_rejected(self):
        anon = APIClient()
        resp = anon.get(self.url, data={"start_date": "2026-01-01"})
        self.assertIn(
            resp.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_default_rolling_window_and_trend_weeks(self):
        """When only dates are supplied, the serializer fills in the
        documented defaults (rolling_window_weeks=4, trend_weeks=13)."""
        start = timezone.localdate() - timedelta(days=30)
        resp = self._get({"start_date": start.isoformat()})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        body = resp.json()
        self.assertEqual(body["period"]["rolling_window_weeks"], 4)
        self.assertEqual(body["period"]["trend_weeks"], 13)
        self.assertEqual(len(body["trend"]["weeks"]), 13)
