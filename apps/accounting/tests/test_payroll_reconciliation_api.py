"""API-level tests for the payroll-reconciliation report endpoints.

The service math is covered in test_payroll_reconciliation_service.py; these
pin the wire: auth, parameter validation, and the response envelope of both
GET /reports/payroll-reconciliation/ and GET /reports/payroll-date-range/.
"""

from datetime import date

import pytest
from django.test import Client

from apps.company.tests.job_fixtures import seed_job_prereqs
from apps.core.models import CompanyDefaults

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

RECON_URL = "/api/accounting/reports/payroll-reconciliation/"
RANGE_URL = "/api/accounting/reports/payroll-date-range/"
PARAMS = {"start_date": "2026-06-03", "end_date": "2026-06-17"}


@pytest.fixture(autouse=True)
def _payroll_window() -> None:
    seed_job_prereqs()
    defaults = CompanyDefaults.get_solo()
    defaults.xero_payroll_start_date = date(2025, 8, 11)
    defaults.save()


class TestPayrollDateRange:
    def test_requires_authentication(self) -> None:
        assert Client().get(RANGE_URL, PARAMS).status_code == 401

    def test_aligns_to_monday_and_sunday(self, authenticated_client: Client) -> None:
        body = authenticated_client.get(RANGE_URL, PARAMS).json()
        # 2026-06-03 is a Wednesday -> Monday 2026-06-01;
        # 2026-06-17 is a Wednesday -> Sunday 2026-06-21.
        assert body == {"aligned_start": "2026-06-01", "aligned_end": "2026-06-21"}

    def test_start_is_floored_to_the_payroll_window(self, authenticated_client: Client) -> None:
        body = authenticated_client.get(
            RANGE_URL, {"start_date": "2024-01-01", "end_date": "2026-06-17"}
        ).json()
        # 2025-08-11 is already a Monday.
        assert body["aligned_start"] == "2025-08-11"

    def test_missing_or_inverted_params_are_rejected(self, authenticated_client: Client) -> None:
        assert authenticated_client.get(RANGE_URL).status_code == 422
        assert (
            authenticated_client.get(
                RANGE_URL, {"start_date": "2026-06-17", "end_date": "2026-06-03"}
            ).status_code
            == 422
        )


class TestPayrollReconciliation:
    def test_requires_authentication(self) -> None:
        assert Client().get(RECON_URL, PARAMS).status_code == 401

    def test_empty_window_returns_the_full_shape(self, authenticated_client: Client) -> None:
        resp = authenticated_client.get(RECON_URL, PARAMS)
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["weeks"] == []
        assert body["staff_summaries"] == []
        assert body["heatmap"] == {"staff_names": [], "rows": []}
        assert body["grand_totals"] == {
            "xero_gross": 0.0,
            "jm_cost": 0.0,
            "diff": 0.0,
            "diff_pct": 0.0,
        }

    def test_missing_params_are_rejected(self, authenticated_client: Client) -> None:
        assert authenticated_client.get(RECON_URL).status_code == 422
