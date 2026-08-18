"""API tests for the Xero Payroll pay-run surface.

These assert OUR half: the ``XeroPayRun`` mirror, the postable-week rule, the
deep link, the posting-task registration, and the translation between the
provider's dataclasses and the wire. The provider is a fake injected explicitly
by ``fake_provider`` below, so what is asserted is our mapping and nothing else.

Whether Xero actually accepts any of it is not knowable here and is not
attempted — that is ``apps/xero/tests/test_payroll_integration.py``, which
calls the real tenant (ADR 0050). These tests previously leaned on
``settings_test`` globally pinning ``XERO_READONLY``, which quietly turned them
into assertions about a stub's fabricated return values.
"""

import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.db.models import Model
from django.test import Client

from apps.accounting.types import (
    PayrollMirrorScope,
    PayRunRef,
    PayRunSyncResult,
    StaffWeekPosting,
    StaffWeekPostResult,
)
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.timesheet import tasks
from apps.timesheet.services import payroll_progress, payroll_service

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.timesheet.tests.urls"),
]

SHORTCODE = "!TEST"


def _pay_run_model() -> type[Model]:
    """Resolve XeroPayRun dynamically: the layer contract forbids the import."""
    return django_apps.get_model("xero", "XeroPayRun")


class _FakeProvider:
    """An accounting provider with known answers, so the mapping is what is tested."""

    provider_name = "Fake"
    supports_payroll = True

    def __init__(self) -> None:
        self.pay_run_id = uuid.uuid4()
        #: Opus: Set per test; the wire shaping is what these tests assert.
        self.week_status: list[StaffWeekPosting] = []

    def payroll_connection_id(self) -> str:
        return "tenant-1"

    def sync_payroll_mirror(self, connection_id: str, scope: PayrollMirrorScope) -> None:
        del connection_id, scope

    def create_pay_run(self, week_start_date: date) -> PayRunRef:
        return PayRunRef(
            pay_run_id=str(self.pay_run_id),
            payroll_calendar_id=str(uuid.uuid4()),
            period_start_date=week_start_date,
            period_end_date=week_start_date + timedelta(days=6),
            payment_date=week_start_date + timedelta(days=9),
            pay_run_status="Draft",
            pay_run_type="Scheduled",
        )

    def refresh_pay_runs(self) -> PayRunSyncResult:
        return PayRunSyncResult(fetched=7, created=2, updated=1)

    def post_payroll_week(
        self,
        connection_id: str,  # noqa: ARG002 -- Opus: part of the provider signature; the real provider refuses a mismatch
        staff_ids: Sequence[uuid.UUID],
        week_start_date: date,  # noqa: ARG002 -- Opus: part of the provider signature; this fake answers per staff member
    ) -> Iterator[StaffWeekPostResult]:
        for staff_id in staff_ids:
            yield StaffWeekPostResult(
                staff_id=str(staff_id), staff_name="Wendy Workshop", success=True
            )

    def week_posting_status(
        self,
        week_start_date: date,  # noqa: ARG002 -- Opus: part of the provider signature; this fake answers for a fixed week
    ) -> list[StaffWeekPosting]:
        return list(self.week_status)


# Opus: docstring rationale unratified (ADR 0051).
@pytest.fixture(autouse=True)
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> _FakeProvider:
    """Inject the fake wherever a payroll consumer resolves its provider.

    Both call sites are patched because Celery runs eagerly under the test
    settings, so the POST endpoint's task executes inline and resolves its own
    provider.
    """
    provider = _FakeProvider()
    for module in ("apps.timesheet.services.payroll_service", "apps.timesheet.tasks"):
        monkeypatch.setattr(f"{module}.get_provider", lambda: provider)
    return provider


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
    """The endpoints' translation of what the provider returned."""

    @pytest.mark.usefixtures("payroll_defaults")
    def test_create_pay_run_answers_with_the_created_run(
        self, manage_client: Client, fake_provider: _FakeProvider
    ) -> None:
        response = manage_client.post(
            "/api/timesheets/payroll/pay-runs/create",
            data={"week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["period_start_date"] == "2026-05-04"
        assert body["period_end_date"] == "2026-05-10"
        assert body["status"] == "Draft"
        # Opus: The deep link is ours to build, from the configured shortcode and the
        # id the provider handed back — the one part of this response that is
        # not simply relayed.
        assert body["xero_url"] == (
            f"https://payroll.xero.com/PayRun?CID={SHORTCODE}#payruns/{fake_provider.pay_run_id}"
        )

    def test_create_pay_run_still_validates_the_monday_first(self, manage_client: Client) -> None:
        response = manage_client.post(
            "/api/timesheets/payroll/pay-runs/create",
            data={"week_start_date": "2026-05-06"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "week_start_date must be a Monday"

    def test_refresh_pay_runs_reports_what_moved(self, manage_client: Client) -> None:
        """The counts are relayed, not recomputed — the operator is shown them."""
        response = manage_client.post("/api/timesheets/payroll/pay-runs/refresh")

        assert response.status_code == 200, response.content
        assert response.json() == {"synced": True, "fetched": 7, "created": 2, "updated": 1}


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
        }

    # Opus: docstring rationale unratified (ADR 0051).
    def test_a_broker_that_refuses_the_dispatch_ends_the_run(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """Otherwise the registered run has no publisher and the page spins for 1800s.

        The stream cannot tell a run that never started from a slow one, so the
        only place that knows is here — the dispatch that raised.
        """

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise OSError("Connection refused by the broker")

        # Opus: Watching what is published rather than reading it back by task id:
        # the id is minted inside the call, and the question this test asks is
        # whether ANYTHING terminal was said, not where it was stored.
        published: list[dict[str, object]] = []
        monkeypatch.setattr(
            payroll_progress, "publish", lambda _task_id, event: published.append(event)
        )
        monkeypatch.setattr(tasks.post_payroll_week_task, "delay", refuse)

        with pytest.raises(OSError, match="Connection refused"):
            payroll_service.start_post_week_task([worker.id], date(2026, 5, 4))

        assert published[-2]["event"] == "error"
        assert "Could not start the posting run" in str(published[-2]["message"])
        assert published[-1] == {"event": "done", "successful": 0, "failed": 1}

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


class TestWeekStatus:
    """`GET /timesheets/payroll/week-status/` — what Xero holds, beside what we recorded.

    ADR 0007 puts this on its own endpoint so the weekly grid keeps rendering
    when Xero is unreachable, and the panel asks for it explicitly because the
    read costs one Xero call per staff member.
    """

    def _posting(self, *, posted: bool, staff_id: str = "staff-1") -> StaffWeekPosting:
        return StaffWeekPosting(
            staff_id=staff_id,
            posted=posted,
            timesheet_status="Approved" if posted else None,
            posted_timesheet_hours=Decimal("8.000") if posted else Decimal("0"),
            posted_leave_hours=Decimal("0"),
            recorded_timesheet_hours=Decimal("8.000") if posted else Decimal("0"),
            recorded_leave_hours=Decimal("0"),
        )

    def test_both_sides_reach_the_wire_as_numbers(
        self, manage_client: Client, fake_provider: _FakeProvider
    ) -> None:
        """Quantities are JSON numbers, not the strings a bare Decimal produces (ADR 0046)."""
        fake_provider.week_status = [self._posting(posted=True)]

        body = manage_client.get(
            "/api/timesheets/payroll/week-status/?week_start_date=2026-05-04"
        ).json()

        assert body["week_start_date"] == "2026-05-04"
        [row] = body["staff"]
        assert row["posted_timesheet_hours"] == 8.0
        assert isinstance(row["posted_timesheet_hours"], float)
        assert row["recorded_timesheet_hours"] == 8.0
        assert row["matches"] is True

    # Opus: docstring rationale unratified (ADR 0051).
    def test_a_nil_week_with_no_timesheet_is_reported_as_a_mismatch(
        self, manage_client: Client, fake_provider: _FakeProvider
    ) -> None:
        """The state that overpays, and the one that used to read as agreement.

        All four figures are zero, so comparing hours alone called it a match —
        the row then vanished from the panel. Without a timesheet Xero pays the
        pay-template default, typically a full week nobody worked.
        """
        fake_provider.week_status = [self._posting(posted=False)]

        body = manage_client.get(
            "/api/timesheets/payroll/week-status/?week_start_date=2026-05-04"
        ).json()

        [row] = body["staff"]
        assert row["posted"] is False
        assert row["matches"] is False

    def test_a_non_monday_is_refused(self, manage_client: Client) -> None:
        """Xero pay periods are Monday-anchored; anything else is a different week."""
        response = manage_client.get(
            "/api/timesheets/payroll/week-status/?week_start_date=2026-05-05"
        )

        assert response.status_code == 400

    def test_an_unparseable_date_is_refused(self, manage_client: Client) -> None:
        response = manage_client.get(
            "/api/timesheets/payroll/week-status/?week_start_date=nonsense"
        )

        assert response.status_code == 400
