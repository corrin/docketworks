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
from datetime import date

import pytest
from django.test import Client

from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.timesheet import tasks
from apps.timesheet.services import payroll_runs, payroll_service
from apps.timesheet.tests.conftest import FakePayrollProvider, make_pay_run, make_week_posting

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.timesheet.tests.urls"),
]

SHORTCODE = "!TEST"


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakePayrollProvider:
    """Inject the fake wherever a payroll consumer resolves its provider.

    Opus: Both call sites are patched because Celery runs eagerly under the test
    settings, so the POST endpoint's task executes inline and resolves its own
    provider.
    """
    provider = FakePayrollProvider()
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


class TestPayRunList:
    def test_lists_the_local_mirror_with_deep_links(
        self, manage_client: Client, payroll_defaults: uuid.UUID
    ) -> None:
        run = make_pay_run(calendar_id=payroll_defaults, week_start=date(2026, 5, 4))

        response = manage_client.get("/api/timesheets/payroll/pay-runs/")

        assert response.status_code == 200, response.content
        body = response.json()
        [row] = body["pay_runs"]
        assert row["xero_id"] == str(run.xero_id)
        assert row["pay_run_status"] == "Draft"
        assert row["xero_url"] == (
            f"https://payroll.xero.com/PayRun?CID={SHORTCODE}#payruns/{run.xero_id}"
        )

    def test_open_draft_is_the_postable_week(
        self, manage_client: Client, payroll_defaults: uuid.UUID
    ) -> None:
        make_pay_run(calendar_id=payroll_defaults, week_start=date(2026, 5, 4))

        body = manage_client.get("/api/timesheets/payroll/pay-runs/").json()

        assert body["next_postable_week_start_date"] == "2026-05-04"
        assert body["next_postable_week_end_date"] == "2026-05-10"

    def test_without_a_draft_the_week_after_the_latest_run_is_postable(
        self, manage_client: Client, payroll_defaults: uuid.UUID
    ) -> None:
        make_pay_run(calendar_id=payroll_defaults, week_start=date(2026, 4, 27), status="Posted")

        body = manage_client.get("/api/timesheets/payroll/pay-runs/").json()

        assert body["next_postable_week_start_date"] == "2026-05-04"
        assert body["next_postable_week_end_date"] == "2026-05-10"

    def test_pay_runs_on_another_calendar_are_ignored(
        self, manage_client: Client, payroll_defaults: uuid.UUID
    ) -> None:
        make_pay_run(calendar_id=payroll_defaults, week_start=date(2026, 5, 4))
        make_pay_run(calendar_id=uuid.uuid4(), week_start=date(2026, 5, 4))

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


class TestPostStaffWeek:
    @pytest.mark.usefixtures("payroll_defaults", "worker")
    def test_it_answers_with_the_runs_opening_document(self, manage_client: Client) -> None:
        """The document, not a task id and a stream URL.

        Opus: The panel renders "0 of N" from this before any push arrives, and the
        same shape is what the poll and the stream carry — so there is one
        contract rather than a URL the client had to follow and a payload only
        hand-written TypeScript described.

        Fable: The request names only the week; the one displayable staff member
        is the server's own roster answer, which is why total is 1 without the
        client having said so.
        """
        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        run = response.json()["run"]
        assert run["week_start_date"] == "2026-05-04"
        assert run["status"] == "running"
        assert run["total"] == 1
        assert run["results"] == []

    @pytest.mark.usefixtures("worker")
    def test_a_week_that_is_not_the_postable_week_is_refused_before_any_posting(
        self, manage_client: Client, payroll_defaults: uuid.UUID, fake_provider: FakePayrollProvider
    ) -> None:
        """The postable-week rule is the server's, enforced on a refreshed mirror.

        Fable: The panel's banner reads a mirror that may be an hour stale, so
        it is advisory; the POST refreshes the mirror itself and refuses with
        the current answer. The refusal must cost nothing irreversible — no
        posting run reaches the provider — and must name the week that CAN be
        posted, because "no" without "which" sends the operator to Xero to find
        out.
        """
        make_pay_run(calendar_id=payroll_defaults, week_start=date(2026, 4, 27), status="Posted")

        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2026-05-11"},
            content_type="application/json",
        )

        assert response.status_code == 400, response.content
        assert "2026-05-04" in response.json()["detail"]
        assert fake_provider.refresh_calls == 1, "the rule must be judged on a refreshed mirror"
        assert fake_provider.posted_weeks == [], "a refused week reached the provider"

    @pytest.mark.usefixtures("worker")
    def test_a_preflight_refusal_releases_the_claim_for_the_next_attempt(
        self, manage_client: Client, payroll_defaults: uuid.UUID, fake_provider: FakePayrollProvider
    ) -> None:
        """Pairs the refusal with its converse: the right week still posts.

        Fable: If the refusal leaked the claim, the operator's corrected click
        would 409 against their own refused attempt until the TTL expired.
        """
        make_pay_run(calendar_id=payroll_defaults, week_start=date(2026, 4, 27), status="Posted")
        refused = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2026-05-11"},
            content_type="application/json",
        )
        assert refused.status_code == 400, refused.content

        corrected = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        assert corrected.status_code == 200, corrected.content
        assert fake_provider.posted_weeks == [date(2026, 5, 4)]

    @pytest.mark.usefixtures("payroll_defaults", "worker")
    def test_posting_is_refused_while_another_run_holds_the_calendar(
        self, manage_client: Client
    ) -> None:
        """Two runs against one calendar can pay a week twice, or half of it.

        Opus: The claim is held directly rather than by starting a real first run,
        because the test settings run Celery eagerly — an inline first run has
        already finished and released by the time a second request arrives, so
        two POSTs cannot express "while one is live" at all.

        Refused HERE, synchronously, with the live run named. The shape this
        replaces refused inside the task, which meant inventing a second run,
        writing a fabricated failure into it, and making the client open a
        stream to discover it had been refused.
        """
        live = str(uuid.uuid4())
        assert payroll_runs.acquire_run_claim("tenant-1", live) is None

        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        assert response.status_code == 409, response.content
        assert live in response.json()["detail"]

    @pytest.mark.usefixtures("payroll_defaults", "worker")
    def test_the_run_is_readable_without_the_id_it_was_given(self, manage_client: Client) -> None:
        """What makes a reload rejoin a live run."""
        manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        response = manage_client.get("/api/timesheets/payroll/runs/")

        assert response.status_code == 200, response.content
        assert response.json()["post"]["week_start_date"] == "2026-05-04"

    @pytest.mark.usefixtures("payroll_defaults", "worker")
    def test_a_broker_that_refuses_the_dispatch_ends_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise the registered run has no publisher and the page spins for 1800s.

        Opus: The stream cannot tell a run that never started from a slow one, so the
        only place that knows is here — the dispatch that raised. Releasing the
        claim matters as much as closing the run: without it the refusal would
        block payroll until the claim's TTL expired.
        """

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise OSError("Connection refused by the broker")

        monkeypatch.setattr(tasks.post_payroll_week_task, "delay", refuse)

        with pytest.raises(OSError, match="Connection refused"):
            payroll_service.start_post_week_task(date(2026, 5, 4))

        run = payroll_service.current_runs().post
        assert run is not None
        assert run.status == "failed"
        assert "Could not start the posting run" in str(run.message)

    @pytest.mark.usefixtures("payroll_defaults")
    def test_a_week_with_no_staff_is_400(self, manage_client: Client) -> None:
        """No displayable staff in the week means there is nothing to post.

        Fable: The roster is the server's answer now, so this refusal is too —
        the client used to detect it by noticing its own relayed list was
        empty.
        """
        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2026-05-04"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "There are no staff to post for this week."

    @pytest.mark.usefixtures("worker")
    def test_a_week_before_xero_payroll_started_is_refused_after_the_refresh(
        self, manage_client: Client, payroll_defaults: uuid.UUID, fake_provider: FakePayrollProvider
    ) -> None:
        """Nothing predating the payroll start is postable, whatever the calendar says.

        Fable: This guard is what makes the refusal independent of calendar
        state — the postable-week rule goes silent when the calendar is empty
        and its anchor is unreachable — and it is why the E2E harness's
        mirror-refresh probe (a deliberately ancient week) is a GUARANTEED
        refusal. It must fire AFTER the refresh, or the probe would stop
        refreshing anything.
        """
        del payroll_defaults
        defaults = CompanyDefaults.get_solo()
        defaults.xero_payroll_start_date = date(2025, 8, 11)
        defaults.save(update_fields=["xero_payroll_start_date"])

        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2001-01-01"},
            content_type="application/json",
        )

        assert response.status_code == 400, response.content
        assert "2025-08-11" in response.json()["detail"]
        assert fake_provider.refresh_calls == 1, "the ancient-week refusal must still refresh"
        assert fake_provider.posted_weeks == []

    def test_non_monday_is_400(self, manage_client: Client) -> None:
        response = manage_client.post(
            "/api/timesheets/payroll/post-staff-week/",
            data={"week_start_date": "2026-05-06"},
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

    def test_both_sides_reach_the_wire_as_numbers(
        self, manage_client: Client, fake_provider: FakePayrollProvider
    ) -> None:
        """Quantities are JSON numbers, not the strings a bare Decimal produces (ADR 0046)."""
        fake_provider.week_status = [
            make_week_posting(posted=True, posted_timesheet="8.000", recorded_timesheet="8.000")
        ]

        body = manage_client.get(
            "/api/timesheets/payroll/week-status/?week_start_date=2026-05-04"
        ).json()

        assert body["week_start_date"] == "2026-05-04"
        [row] = body["staff"]
        assert row["posted_timesheet_hours"] == 8.0
        assert isinstance(row["posted_timesheet_hours"], float)
        assert row["recorded_timesheet_hours"] == 8.0
        assert row["matches"] is True

    def test_a_nil_week_with_no_timesheet_is_reported_as_a_mismatch(
        self, manage_client: Client, fake_provider: FakePayrollProvider
    ) -> None:
        """The state that overpays, and the one that used to read as agreement.

        Opus: All four figures are zero, so comparing hours alone called it a match —
        the row then vanished from the panel. Without a timesheet Xero pays the
        pay-template default, typically a full week nobody worked.
        """
        fake_provider.week_status = [make_week_posting(posted=False)]

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
