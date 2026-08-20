"""API-level tests for the payroll-reconciliation report endpoints.

The service math is covered in test_payroll_reconciliation_service.py; these
pin the wire: auth, parameter validation, and the response envelope of
GET /reports/payroll-reconciliation/, its /week/ sibling, and
GET /reports/payroll-date-range/.
"""

from datetime import date

import pytest
from django.test import Client

from apps.accounting.services import payroll_reconciliation_service
from apps.company.tests.conftest import authenticate
from apps.core.models import CompanyDefaults
from apps.timesheet.tests.conftest import make_staff

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

RECON_URL = "/api/accounting/reports/payroll-reconciliation/"
WEEK_URL = "/api/accounting/reports/payroll-reconciliation/week/"
RANGE_URL = "/api/accounting/reports/payroll-date-range/"
PARAMS = {"start_date": "2026-06-03", "end_date": "2026-06-17"}
WEEK_PARAMS = {"week_start_date": "2026-06-01"}

PAYROLL_ENDPOINTS = (
    (RANGE_URL, PARAMS),
    (RECON_URL, PARAMS),
    (WEEK_URL, WEEK_PARAMS),
)


@pytest.fixture(autouse=True)
def _payroll_window() -> None:
    defaults = CompanyDefaults.get_solo()
    defaults.xero_payroll_start_date = date(2025, 8, 11)
    defaults.save()


@pytest.fixture
def payroll_client() -> Client:
    """A superuser's browser session — the only role that may read pay data."""
    client = Client()
    authenticate(client, make_staff("payroll-reports@example.com", is_superuser=True))
    return client


class TestPayrollReportAuth:
    """Per-employee pay is superuser data on every surface, these included.

    The refusal is asserted per endpoint; the converse (a superuser is served)
    rides in the shape tests below, which would fail 403 if the gate refused
    everyone.
    """

    @pytest.mark.parametrize(("url", "params"), PAYROLL_ENDPOINTS)
    def test_anonymous_is_rejected(self, url: str, params: dict[str, str]) -> None:
        assert Client().get(url, params).status_code == 401

    @pytest.mark.parametrize(("url", "params"), PAYROLL_ENDPOINTS)
    def test_workshop_staff_are_rejected(self, url: str, params: dict[str, str]) -> None:
        client = Client()
        authenticate(client, make_staff("workshop-worker@example.com"))
        assert client.get(url, params).status_code == 403

    @pytest.mark.parametrize(("url", "params"), PAYROLL_ENDPOINTS)
    def test_office_staff_are_not_enough(self, url: str, params: dict[str, str]) -> None:
        client = Client()
        authenticate(client, make_staff("office-only@example.com", is_office_staff=True))
        assert client.get(url, params).status_code == 403


class TestWeekReconciliationEndpoint:
    def test_a_superuser_is_served_the_week_shape(
        self, payroll_client: Client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The converse of the auth refusals: the gate admits the one role it should.

        Fable: Without this, an auth class that refused EVERYONE on this route
        would pass every test the endpoint has — the 401/403 assertions are
        satisfied by any refusal.
        """
        provider = type(
            "_Provider", (), {"get_pay_slips_for_week": staticmethod(lambda _week: [])}
        )()
        monkeypatch.setattr(payroll_reconciliation_service, "get_provider", lambda: provider)

        resp = payroll_client.get(WEEK_URL, WEEK_PARAMS)

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["xero_source"] == "no_pay_run"
        assert body["unposted_count"] == 0
        assert body["week"]["week_start"] == "2026-06-01"


class TestPayrollDateRange:
    def test_aligns_to_monday_and_sunday(self, payroll_client: Client) -> None:
        body = payroll_client.get(RANGE_URL, PARAMS).json()
        # 2026-06-03 is a Wednesday -> Monday 2026-06-01;
        # 2026-06-17 is a Wednesday -> Sunday 2026-06-21.
        assert body == {"aligned_start": "2026-06-01", "aligned_end": "2026-06-21"}

    def test_start_is_floored_to_the_payroll_window(self, payroll_client: Client) -> None:
        body = payroll_client.get(
            RANGE_URL, {"start_date": "2024-01-01", "end_date": "2026-06-17"}
        ).json()
        # 2025-08-11 is already a Monday.
        assert body["aligned_start"] == "2025-08-11"

    def test_missing_or_inverted_params_are_rejected(self, payroll_client: Client) -> None:
        assert payroll_client.get(RANGE_URL).status_code == 422
        assert (
            payroll_client.get(
                RANGE_URL, {"start_date": "2026-06-17", "end_date": "2026-06-03"}
            ).status_code
            == 422
        )


class TestPayrollReconciliation:
    def test_empty_window_returns_the_full_shape(self, payroll_client: Client) -> None:
        resp = payroll_client.get(RECON_URL, PARAMS)
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["weeks"] == []
        assert body["staff_summaries"] == []
        assert body["heatmap"] == {"columns": [], "rows": []}
        assert body["grand_totals"] == {
            "xero_gross": 0.0,
            "jm_cost": 0.0,
            "diff": 0.0,
            "diff_pct": 0.0,
        }

    def test_missing_params_are_rejected(self, payroll_client: Client) -> None:
        assert payroll_client.get(RECON_URL).status_code == 422
