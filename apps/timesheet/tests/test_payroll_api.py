"""API tests for the Xero Payroll pay-run surface.

The local half (the ``XeroPayRun`` mirror, the postable-week rule, the deep
link, the posting-task registration) is real code and is asserted here. The
Xero half is a Phase 4 seam and is asserted to fail loudly rather than pretend.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from django.apps import apps as django_apps
from django.db.models import Model
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.timesheet.services import payroll_progress, payroll_service

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.timesheet.tests.urls"),
]

SHORTCODE = "!TEST"


def _pay_run_model() -> type[Model]:
    """Resolve XeroPayRun dynamically: the layer contract forbids the import."""
    return django_apps.get_model("xero", "XeroPayRun")


@pytest.fixture
def payroll_defaults(company: Company) -> uuid.UUID:
    """Configure the calendar id and shortcode the pay-run surface needs."""
    assert company is not None  # seeds the CompanyDefaults singleton properly
    defaults = CompanyDefaults.get_solo()
    defaults.xero_payroll_calendar_id = uuid.uuid4()
    defaults.xero_shortcode = SHORTCODE
    defaults.save(update_fields=["xero_payroll_calendar_id", "xero_shortcode"])
    return defaults.xero_payroll_calendar_id


def _make_pay_run(
    calendar_id: uuid.UUID,
    *,
    start: date,
    end: date,
    status: str = "Draft",
) -> uuid.UUID:
    """Create a mirror row and return its Xero id (the only field tests assert on)."""
    xero_id = uuid.uuid4()
    _pay_run_model()._default_manager.create(
        xero_id=xero_id,
        xero_tenant_id="tenant-1",
        payroll_calendar_id=calendar_id,
        period_start_date=start,
        period_end_date=end,
        payment_date=end,
        pay_run_status=status,
        raw_json={},
        xero_last_modified=datetime(2026, 5, 13, tzinfo=UTC),
    )
    return xero_id


class TestPayRunList:
    def test_lists_the_local_mirror_with_deep_links(
        self, manage_client: Client, payroll_defaults: uuid.UUID
    ) -> None:
        xero_id = _make_pay_run(payroll_defaults, start=date(2026, 5, 4), end=date(2026, 5, 10))

        response = manage_client.get("/api/timesheets/payroll/pay-runs/")

        assert response.status_code == 200, response.content
        body = response.json()
        [row] = body["pay_runs"]
        assert row["xero_id"] == str(xero_id)
        assert row["pay_run_status"] == "Draft"
        assert row["xero_url"] == (
            f"https://payroll.xero.com/PayRun?CID={SHORTCODE}#payruns/{xero_id}"
        )

    def test_open_draft_is_the_postable_week(
        self, manage_client: Client, payroll_defaults: uuid.UUID
    ) -> None:
        _make_pay_run(payroll_defaults, start=date(2026, 5, 4), end=date(2026, 5, 10))

        body = manage_client.get("/api/timesheets/payroll/pay-runs/").json()

        assert body["next_postable_week_start_date"] == "2026-05-04"
        assert body["next_postable_week_end_date"] == "2026-05-10"

    def test_without_a_draft_the_week_after_the_latest_run_is_postable(
        self, manage_client: Client, payroll_defaults: uuid.UUID
    ) -> None:
        _make_pay_run(
            payroll_defaults,
            start=date(2026, 4, 27),
            end=date(2026, 5, 3),
            status="Posted",
        )

        body = manage_client.get("/api/timesheets/payroll/pay-runs/").json()

        assert body["next_postable_week_start_date"] == "2026-05-04"
        assert body["next_postable_week_end_date"] == "2026-05-10"

    def test_pay_runs_on_another_calendar_are_ignored(
        self, manage_client: Client, payroll_defaults: uuid.UUID
    ) -> None:
        _make_pay_run(payroll_defaults, start=date(2026, 5, 4), end=date(2026, 5, 10))
        _make_pay_run(uuid.uuid4(), start=date(2026, 5, 4), end=date(2026, 5, 10))

        body = manage_client.get("/api/timesheets/payroll/pay-runs/").json()

        assert len(body["pay_runs"]) == 1

    def test_missing_calendar_configuration_fails_loudly(self, manage_client: Client) -> None:
        response = manage_client.get("/api/timesheets/payroll/pay-runs/")

        assert response.status_code == 500
        assert "xero_payroll_calendar_id not configured" in response.json()["detail"]

    @pytest.mark.usefixtures("payroll_defaults")
    def test_empty_calendar_returns_200_with_null_postable_dates(
        self, manage_client: Client
    ) -> None:
        """A read endpoint must not die because a write-side Xero seam is unported.

        v1 filled the first postable week from the Xero calendar's anchor period;
        that lookup is Phase 4, so v2 reports no postable week — which is already
        part of the v1 contract (the client falls back to the current week).
        """
        response = manage_client.get("/api/timesheets/payroll/pay-runs/")

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["pay_runs"] == []
        assert body["next_postable_week_start_date"] is None
        assert body["next_postable_week_end_date"] is None


class TestPayRunWrites:
    """The suite runs under XERO_READONLY, so writes are suppressed, not sent.

    That is the point of the read-only provider: the endpoint contract is
    exercised end to end while nothing reaches a Xero tenant.
    """

    @pytest.mark.usefixtures("payroll_defaults")
    def test_create_pay_run_answers_with_the_created_run(self, manage_client: Client) -> None:
        response = manage_client.post(
            "/api/timesheets/payroll/pay-runs/create",
            data={"week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["period_start_date"] == "2026-05-04"
        assert body["period_end_date"] == "2026-05-10"
        # Xero pays the Wednesday after the period ends.
        assert body["payment_date"] == "2026-05-13"
        assert body["status"] == "Draft"

    def test_create_pay_run_still_validates_the_monday_first(self, manage_client: Client) -> None:
        response = manage_client.post(
            "/api/timesheets/payroll/pay-runs/create",
            data={"week_start_date": "2026-05-06"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "week_start_date must be a Monday"

    def test_refresh_pay_runs_reports_what_moved(self, manage_client: Client) -> None:
        response = manage_client.post("/api/timesheets/payroll/pay-runs/refresh")

        assert response.status_code == 200, response.content
        assert response.json() == {"synced": True, "fetched": 0, "created": 0, "updated": 0}


class TestPostStaffWeek:
    def test_registers_a_task_and_returns_its_stream_url(
        self, manage_client: Client, worker: Staff
    ) -> None:
        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"staff_ids": [str(worker.id)], "week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        task_id = body["task_id"]
        assert body["stream_url"] == (f"/api/timesheets/payroll/post-staff-week/stream/{task_id}/")
        assert payroll_progress.get_task(task_id) == {
            "staff_ids": [str(worker.id)],
            "week_start_date": "2026-05-04",
            "status": "pending",
        }

    def test_empty_staff_ids_is_400(self, manage_client: Client) -> None:
        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"staff_ids": [], "week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "staff_ids is required"

    def test_non_monday_is_400(self, manage_client: Client, worker: Staff) -> None:
        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"staff_ids": [str(worker.id)], "week_start_date": "2026-05-06"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "week_start_date must be a Monday"


@pytest.mark.usefixtures("company")
class TestPayrollDeepLink:
    def test_missing_shortcode_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="Xero shortcode not configured"):
            payroll_service.build_xero_payroll_url(uuid.uuid4())
