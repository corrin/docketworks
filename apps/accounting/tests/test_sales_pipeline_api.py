"""API-level tests for GET /api/accounting/reports/sales-pipeline/.

Pins response shape, end-date defaulting, each validation failure mode, and the
persisted-error 500 contract. Invalid parameters use the standard 422 envelope.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from apps.company.tests.job_fixtures import seed_job_prereqs

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

URL = "/api/accounting/reports/sales-pipeline/"


@pytest.fixture(autouse=True)
def _company_defaults() -> None:
    """The report reads CompanyDefaults, as production always can."""
    seed_job_prereqs()


class TestSalesPipelineAPI:
    def test_valid_request_returns_all_sections(self, authenticated_client: Client) -> None:
        resp = authenticated_client.get(
            URL,
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "rolling_window_weeks": "4",
                "trend_weeks": "4",
            },
        )
        assert resp.status_code == 200, resp.content
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
            assert key in body, f"missing top-level key {key!r}"
        assert len(body["trend"]["weeks"]) == 4
        assert len(body["trend"]["rolling_average"]) == 4

    def test_omitted_end_date_defaults_to_today(self, authenticated_client: Client) -> None:
        resp = authenticated_client.get(URL, {"start_date": "2026-01-01"})
        assert resp.status_code == 200, resp.content
        assert resp.json()["period"]["end_date"] == timezone.localdate().isoformat()

    @pytest.mark.parametrize(
        "params",
        [
            {"end_date": "2026-02-01"},  # missing start_date
            {"start_date": "not-a-date"},
            {"start_date": "2026-01-01", "end_date": "2026-13-40"},
            {"start_date": "2026-02-10", "end_date": "2026-02-01"},  # inverted
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "rolling_window_weeks": "0",
            },
            {"start_date": "2026-01-01", "end_date": "2026-01-31", "trend_weeks": "0"},
        ],
    )
    def test_invalid_params_are_rejected(
        self, authenticated_client: Client, params: dict[str, str]
    ) -> None:
        assert authenticated_client.get(URL, params).status_code == 422

    def test_unexpected_service_failure_persists_and_returns_error_id(
        self, authenticated_client: Client
    ) -> None:
        with patch(
            "apps.accounting.api.sales_pipeline_service.SalesPipelineService.get_report",
            side_effect=RuntimeError("boom"),
        ):
            resp = authenticated_client.get(
                URL, {"start_date": "2026-01-01", "end_date": "2026-01-31"}
            )
        assert resp.status_code == 500, resp.content
        body = resp.json()
        assert body["detail"] == "boom"
        assert body["error_id"]

    def test_unauthenticated_request_is_rejected(self) -> None:
        assert Client().get(URL, {"start_date": "2026-01-01"}).status_code == 401

    def test_default_rolling_window_and_trend_weeks(self, authenticated_client: Client) -> None:
        start = timezone.localdate() - timedelta(days=30)
        resp = authenticated_client.get(URL, {"start_date": start.isoformat()})
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["period"]["rolling_window_weeks"] == 4
        assert body["period"]["trend_weeks"] == 13
        assert len(body["trend"]["weeks"]) == 13
