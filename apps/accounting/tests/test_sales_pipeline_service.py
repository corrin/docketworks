"""Service-level tests for the Sales Pipeline Report.

Covers every bullet from the v1 requirements plan
``docs/plans/2026-04-16-sales-pipeline-report.md`` "Service-level
tests" section. Builds JobEvent fixtures directly so that historical
timestamps and ``delta_after`` values can be controlled precisely.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.services.sales_pipeline_service import SalesPipelineService
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import seed_job_prereqs
from apps.core.models import CompanyDefaults
from apps.job.models import Job, JobEvent
from apps.job.models.costing import CostSet

pytestmark = [pytest.mark.django_db]

NZ_TZ = ZoneInfo("Pacific/Auckland")


def _nz_dt(d: date, hour: int = 12) -> datetime:
    """Build an NZ-local datetime at the given hour (default noon)."""
    return datetime.combine(d, time(hour=hour), tzinfo=NZ_TZ)


# ─── Fixture builders (ported from v1's SalesPipelineServiceFixturesMixin) ───


def _event_staff(job: Job) -> Staff:
    """The staff member events on this job are attributed to."""
    created_by = job.created_by
    assert created_by is not None
    return created_by


def _make_job(*, name: str, company: Company, created_dt: datetime, staff: Staff) -> Job:
    """Create a job with a deterministic ``job_created`` event at ``created_dt``.

    ``Job.save()`` itself does not emit ``job_created`` — that lives in
    ``job_service.create_job``. The test fixture bypasses the service, so we
    emit the event explicitly at the requested timestamp.
    """
    seed_job_prereqs()
    job = Job(name=name, company=company)
    job.save(staff=staff)
    JobEvent.objects.create(
        job=job,
        event_type="job_created",
        timestamp=created_dt,
        staff=staff,
        detail={
            "job_name": job.name,
            "company_name": company.name if company else "Shop Job",
            "person_name": None,
            "initial_status": job.get_status_display(),
            "pricing_methodology": job.get_pricing_methodology_display(),
        },
        delta_after={"status": job.status},
    )
    return job


def _add_status_change(
    job: Job,
    *,
    old: str,
    new: str,
    at: datetime,
    event_type: str = "status_changed",
) -> JobEvent:
    return JobEvent.objects.create(
        job=job,
        staff=_event_staff(job),
        event_type=event_type,
        timestamp=at,
        delta_before={"status": old},
        delta_after={"status": new},
    )


def _add_quote_accepted(
    job: Job, *, at: datetime, old_status: str = "awaiting_approval"
) -> JobEvent:
    return JobEvent.objects.create(
        job=job,
        staff=_event_staff(job),
        event_type="quote_accepted",
        timestamp=at,
        delta_before={"status": old_status},
        delta_after={"status": "approved"},
    )


def _add_job_rejected(job: Job, *, at: datetime) -> JobEvent:
    return JobEvent.objects.create(
        job=job,
        staff=_event_staff(job),
        event_type="job_rejected",
        timestamp=at,
        delta_before={"status": "awaiting_approval", "rejected_flag": False},
        delta_after={"status": "archived", "rejected_flag": True},
    )


def _attach_quote(job: Job, *, hours: float, rev: float = 0.0) -> CostSet:
    # Job.save() already seeds a rev=1 quote CostSet; update it in place so
    # we don't trip the (job, kind, rev) unique constraint.
    cs = job.latest_quote
    assert cs is not None
    cs.summary = {"cost": 0.0, "rev": rev, "hours": hours}
    cs.save(update_fields=["summary"])
    return cs


def _attach_estimate(job: Job, *, hours: float, rev: float = 0.0) -> CostSet:
    cs = job.latest_estimate
    assert cs is not None
    cs.summary = {"cost": 0.0, "rev": rev, "hours": hours}
    cs.save(update_fields=["summary"])
    return cs


def _detach_summaries(job: Job) -> None:
    """Simulate a job with no usable quote/estimate hours summary."""
    quote = job.latest_quote
    estimate = job.latest_estimate
    assert quote is not None
    assert estimate is not None
    quote.summary = {"cost": 0.0, "rev": 0.0}
    quote.save(update_fields=["summary"])
    estimate.summary = {"cost": 0.0, "rev": 0.0}
    estimate.save(update_fields=["summary"])


# ─── Shared fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def defaults() -> CompanyDefaults:
    """The CompanyDefaults singleton, with the job prerequisites seeded."""
    seed_job_prereqs()
    return CompanyDefaults.get_solo()


@pytest.fixture
def eight_hour_target(defaults: CompanyDefaults) -> CompanyDefaults:
    """CompanyDefaults with the daily approved-hours target the tests assume."""
    defaults.daily_approved_hours_target = Decimal("8.00")
    defaults.save()
    return defaults


@pytest.fixture
def acme() -> Company:
    """The client company jobs hang off (v1's ``_make_client``)."""
    seed_job_prereqs()
    return make_company("Acme Co", email="acme_co@example.com")


class TestScoreboard:
    # v1's setUp built the client company and an 8h/day target for every test.
    pytestmark = pytest.mark.usefixtures("eight_hour_target")

    start = date(2026, 3, 2)  # Monday
    end = date(2026, 3, 6)  # Friday — 5 working days

    def test_status_changed_into_approved_counts(self, acme: Company, staff: Staff) -> None:
        job = _make_job(name="J1", company=acme, created_dt=_nz_dt(date(2026, 1, 5)), staff=staff)
        _attach_quote(job, hours=12.5)
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10)))
        _add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 3, 4))
        )

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        assert rep["scoreboard"]["approved_jobs_count"] == 1
        assert rep["scoreboard"]["approved_hours_total"] == pytest.approx(12.5)
        # Not direct — went through awaiting_approval.
        assert rep["scoreboard"]["direct_jobs_count"] == 0

    def test_quote_accepted_counts(self, acme: Company, staff: Staff) -> None:
        job = _make_job(name="J2", company=acme, created_dt=_nz_dt(date(2026, 1, 5)), staff=staff)
        _attach_quote(job, hours=4.0)
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10)))
        _add_quote_accepted(job, at=_nz_dt(date(2026, 3, 5)))

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        assert rep["scoreboard"]["approved_jobs_count"] == 1
        assert rep["scoreboard"]["approved_hours_total"] == pytest.approx(4.0)

    def test_direct_approved_counts_in_direct_bucket(self, acme: Company, staff: Staff) -> None:
        job = _make_job(name="J3", company=acme, created_dt=_nz_dt(date(2026, 1, 5)), staff=staff)
        _attach_quote(job, hours=6.0)
        # Straight from draft to approved — no awaiting and no quote_accepted.
        _add_status_change(job, old="draft", new="approved", at=_nz_dt(date(2026, 3, 4)))

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        assert rep["scoreboard"]["approved_jobs_count"] == 1
        assert rep["scoreboard"]["direct_jobs_count"] == 1
        assert rep["scoreboard"]["direct_hours"] == pytest.approx(6.0)

    def test_dedupe_approved_then_in_progress_same_period(
        self, acme: Company, staff: Staff
    ) -> None:
        job = _make_job(name="J4", company=acme, created_dt=_nz_dt(date(2026, 1, 5)), staff=staff)
        _attach_quote(job, hours=10.0)
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10)))
        _add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 3, 3))
        )
        _add_status_change(job, old="approved", new="in_progress", at=_nz_dt(date(2026, 3, 5)))

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        assert rep["scoreboard"]["approved_jobs_count"] == 1
        assert rep["scoreboard"]["approved_hours_total"] == pytest.approx(10.0)

    def test_target_reflects_company_defaults(self, eight_hour_target: CompanyDefaults) -> None:
        eight_hour_target.daily_approved_hours_target = Decimal("20.00")
        eight_hour_target.save()

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        # 5 NZ working days x 20 = 100
        assert rep["scoreboard"]["working_days"] == 5
        assert rep["scoreboard"]["target_hours_for_period"] == pytest.approx(100.0)
        assert rep["period"]["daily_approved_hours_target"] == pytest.approx(20.0)

    def test_missing_hours_summary_excludes_and_warns(self, acme: Company, staff: Staff) -> None:
        job = _make_job(
            name="No hours", company=acme, created_dt=_nz_dt(date(2026, 1, 5)), staff=staff
        )
        # Remove hours from the default quote/estimate summaries so hours
        # resolution genuinely fails (Job.save() seeds both with hours=0.0).
        _detach_summaries(job)
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10)))
        _add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 3, 4))
        )

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        assert rep["scoreboard"]["approved_jobs_count"] == 0
        codes = {(w["code"], w["section"]) for w in rep["warnings"]}
        assert ("missing_hours_summary", "scoreboard") in codes


class TestSnapshot:
    def test_replays_to_historical_status_not_live(self, acme: Company, staff: Staff) -> None:
        # Created in draft 2026-01-05, moved to awaiting_approval 2026-02-01,
        # approved 2026-03-15, archived 2026-04-10. As of end_date 2026-02-15
        # the historical state is "awaiting_approval".
        job = _make_job(
            name="Replay job", company=acme, created_dt=_nz_dt(date(2026, 1, 5)), staff=staff
        )
        _attach_quote(job, hours=7.0, rev=2100.0)
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 1)))
        _add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 3, 15))
        )
        _add_status_change(job, old="approved", new="archived", at=_nz_dt(date(2026, 4, 10)))

        # Live job.status reflects the most recent change (archived) — service
        # must use the replay, not job.status.
        job.refresh_from_db()
        assert job.status != "awaiting_approval"

        rep = SalesPipelineService.get_report(date(2026, 1, 1), date(2026, 2, 15), 4, 13)
        assert rep["pipeline_snapshot"]["awaiting_approval"]["count"] == 1
        assert rep["pipeline_snapshot"]["awaiting_approval"]["hours_total"] == pytest.approx(7.0)

    def test_days_in_stage_uses_most_recent_entry(self, acme: Company, staff: Staff) -> None:
        end_date = date(2026, 3, 20)
        # Created in awaiting_approval, bounced back to draft, then back to
        # awaiting_approval. Days-in-stage measured from the latest entry.
        job = _make_job(
            name="Bouncy", company=acme, created_dt=_nz_dt(date(2026, 1, 1)), staff=staff
        )
        # Override creation status to awaiting_approval for this test so the
        # historical replay anchor starts there.
        JobEvent.objects.filter(job=job, event_type="job_created").update(
            delta_after={"status": "awaiting_approval"}
        )
        assert JobEvent.objects.filter(job=job, event_type="job_created").count() == 1
        _attach_quote(job, hours=3.0)
        _add_status_change(job, old="awaiting_approval", new="draft", at=_nz_dt(date(2026, 2, 1)))
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 10)))

        rep = SalesPipelineService.get_report(date(2026, 1, 1), end_date, 4, 13)
        bucket = rep["pipeline_snapshot"]["awaiting_approval"]
        assert bucket["count"] == 1
        assert bucket["jobs"][0]["days_in_stage"] == 10

    def test_draft_uses_estimate_summary_awaiting_uses_quote(
        self, acme: Company, staff: Staff
    ) -> None:
        d_job = _make_job(
            name="DraftJ", company=acme, created_dt=_nz_dt(date(2026, 2, 1)), staff=staff
        )
        _attach_estimate(d_job, hours=2.5)
        # Quote also exists but draft must use estimate
        _attach_quote(d_job, hours=99.9)

        a_job = _make_job(
            name="AwaitJ", company=acme, created_dt=_nz_dt(date(2026, 2, 1)), staff=staff
        )
        _attach_estimate(a_job, hours=99.9)
        _attach_quote(a_job, hours=4.5)
        _add_status_change(a_job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 5)))

        rep = SalesPipelineService.get_report(date(2026, 1, 1), date(2026, 2, 28), 4, 13)
        assert rep["pipeline_snapshot"]["draft"]["hours_total"] == pytest.approx(2.5)
        assert rep["pipeline_snapshot"]["awaiting_approval"]["hours_total"] == pytest.approx(4.5)

    def test_narrowed_fetch_preserves_historical_replay(self, acme: Company, staff: Staff) -> None:
        """A job created long before the reporting window whose transitions
         leave it in a pipeline stage at ``end_date`` must still surface in
         the snapshot. Tier 1 narrows the fetch window to save work, so this
         guards against regressing historical replay for those jobs.

         See ``docs/plans/now-the-performance-concerns-stateful-taco.md``
        .
        """
        job = _make_job(
            name="LongHistory", company=acme, created_dt=_nz_dt(date(2023, 1, 15)), staff=staff
        )
        _attach_quote(job, hours=9.0, rev=1800.0)
        # Transition to awaiting_approval three years before the window.
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2023, 6, 20)))
        # Nothing else happens. Historical state as of 2026-04-30 must still
        # be awaiting_approval, derivable only by fetching the 2023 event.
        start = date(2026, 4, 1)
        end = date(2026, 4, 30)

        rep = SalesPipelineService.get_report(start, end, 4, 4)
        bucket = rep["pipeline_snapshot"]["awaiting_approval"]
        assert bucket["count"] == 1
        assert bucket["hours_total"] == pytest.approx(9.0)

    def test_narrowed_fetch_applies_lower_bound_for_in_window_query(
        self, acme: Company, staff: Staff
    ) -> None:
        """The main events query must carry a ``timestamp >=`` filter so we
        aren't hauling years of history for a short report window. The
        pre-window query that backfills pipeline-stage jobs is allowed to
        run unbounded below.
        """
        # A job entirely outside the reporting window. With narrowing, its
        # events should arrive via the pipeline-stage pre-window backfill
        # (single queryset), not the in-window queryset.
        outside_job = _make_job(
            name="Outside", company=acme, created_dt=_nz_dt(date(2022, 3, 1)), staff=staff
        )
        _attach_estimate(outside_job, hours=2.0)
        _add_status_change(
            outside_job, old="draft", new="awaiting_approval", at=_nz_dt(date(2022, 8, 1))
        )
        _add_status_change(
            outside_job, old="awaiting_approval", new="archived", at=_nz_dt(date(2022, 12, 1))
        )

        start = date(2026, 4, 1)
        end = date(2026, 4, 30)

        with CaptureQueriesContext(connection) as ctx:
            SalesPipelineService.get_report(start, end, 4, 4)

        jobevent_selects = [
            q["sql"]
            for q in ctx.captured_queries
            if '"job_jobevent"' in q["sql"] and q["sql"].lstrip().upper().startswith("SELECT")
        ]
        assert jobevent_selects, "expected JobEvent SELECTs"
        has_lower_bound = any('"timestamp" >=' in q for q in jobevent_selects)
        assert has_lower_bound, (
            "no JobEvent SELECT carried a timestamp >= lower bound — "
            "fetch narrowing regressed. Queries:\n" + "\n".join(jobevent_selects)
        )

    def test_missing_creation_anchor_excludes_and_warns(self, acme: Company, staff: Staff) -> None:
        # Build a job and then delete its job_created event.
        job = _make_job(
            name="Anchorless", company=acme, created_dt=_nz_dt(date(2026, 2, 1)), staff=staff
        )
        _attach_quote(job, hours=5.0)
        JobEvent.objects.filter(job=job, event_type="job_created").delete()
        # Add a status change so the job has events at all
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10)))

        rep = SalesPipelineService.get_report(date(2026, 1, 1), date(2026, 2, 28), 4, 13)
        assert rep["pipeline_snapshot"]["awaiting_approval"]["count"] == 0
        codes = {(w["code"], w["section"]) for w in rep["warnings"]}
        assert ("missing_creation_anchor", "pipeline_snapshot") in codes


class TestVelocity:
    def test_median_p80_sample_size(self, acme: Company, staff: Staff) -> None:
        """Three approvals in period with created→approved deltas of 5, 10, 20 days."""
        for i, gap in enumerate((5, 10, 20)):
            created = date(2026, 2, 1)
            approved_dt = _nz_dt(date(2026, 2, 1) + timedelta(days=gap))
            j = _make_job(name=f"V{i}", company=acme, created_dt=_nz_dt(created), staff=staff)
            _attach_quote(j, hours=1.0)
            _add_status_change(
                j,
                old="draft",
                new="awaiting_approval",
                at=_nz_dt(date(2026, 2, 1) + timedelta(days=1)),
            )
            _add_status_change(j, old="awaiting_approval", new="approved", at=approved_dt)

        rep = SalesPipelineService.get_report(date(2026, 2, 1), date(2026, 2, 28), 4, 13)
        v = rep["velocity"]["created_to_approved"]
        assert v["sample_size"] == 3
        assert v["median_days"] == pytest.approx(10.0)
        # p80 over [5, 10, 20] (n=3, idx round(0.8*2)=2) = 20
        assert v["p80_days"] == pytest.approx(20.0)

    def test_pre_window_creation_resolved_for_in_window_approval(
        self, acme: Company, staff: Staff
    ) -> None:
        """A job created long before the reporting window but approved
        inside it must have its (pre-window) creation event fetched — the
        Tier 1 fetch-narrowing regressed this until the relevant-jobs
        union was added. Job's current status is in_progress/archived,
        so it's NOT a pipeline-stage candidate; inclusion must come via
        the in-window activity set instead.
        """
        job = _make_job(
            name="OldCreatedNowArchived",
            company=acme,
            created_dt=_nz_dt(date(2024, 1, 15)),
            staff=staff,
        )
        _attach_quote(job, hours=4.0)
        # Approved in-period, then archived after the report window — the
        # live status is archived, which previously caused the narrowing to
        # drop this job's pre-window job_created event.
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2024, 3, 1)))
        _add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 2, 10))
        )
        _add_status_change(job, old="approved", new="archived", at=_nz_dt(date(2026, 3, 20)))

        rep = SalesPipelineService.get_report(date(2026, 2, 1), date(2026, 2, 28), 4, 4)
        # Scoreboard counts the approval, not a missing-hours warning.
        assert rep["scoreboard"]["approved_jobs_count"] == 1
        # Velocity created_to_approved gets the full 2-year delta.
        assert rep["velocity"]["created_to_approved"]["sample_size"] == 1
        # Not a false 'direct' — the job had a prior awaiting_approval.
        assert rep["scoreboard"]["direct_jobs_count"] == 0
        # No spurious missing-anchor warnings for this job.
        missing_anchor_codes = {
            w["section"] for w in rep["warnings"] if w["code"] == "missing_creation_anchor"
        }
        assert missing_anchor_codes == set()

    def test_missing_creation_anchor_excludes_and_warns(self, acme: Company, staff: Staff) -> None:
        """A velocity-relevant event in-period on a job missing its
        job_created anchor must produce a warning, not silent exclusion.
        """
        job = _make_job(
            name="VelAnchorless", company=acme, created_dt=_nz_dt(date(2026, 2, 1)), staff=staff
        )
        _attach_quote(job, hours=1.0)
        JobEvent.objects.filter(job=job, event_type="job_created").delete()
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 5)))
        _add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 2, 10))
        )

        rep = SalesPipelineService.get_report(date(2026, 2, 1), date(2026, 2, 28), 4, 13)
        assert rep["velocity"]["created_to_approved"]["sample_size"] == 0
        codes = {(w["code"], w["section"]) for w in rep["warnings"]}
        assert ("missing_creation_anchor", "velocity") in codes


class TestFunnel:
    start = date(2026, 3, 1)
    end = date(2026, 3, 31)

    def test_categorization_is_mutually_exclusive(self, acme: Company, staff: Staff) -> None:
        # Accepted via quote_accepted
        j_acc = _make_job(
            name="Acc", company=acme, created_dt=_nz_dt(date(2026, 3, 2)), staff=staff
        )
        _attach_quote(j_acc, hours=1.0)
        _add_status_change(j_acc, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 5)))
        _add_quote_accepted(j_acc, at=_nz_dt(date(2026, 3, 10)))

        # Rejected
        j_rej = _make_job(
            name="Rej", company=acme, created_dt=_nz_dt(date(2026, 3, 3)), staff=staff
        )
        _attach_quote(j_rej, hours=2.0)
        _add_status_change(j_rej, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 6)))
        _add_job_rejected(j_rej, at=_nz_dt(date(2026, 3, 15)))

        # Waiting
        j_wait = _make_job(
            name="Wait", company=acme, created_dt=_nz_dt(date(2026, 3, 4)), staff=staff
        )
        _attach_quote(j_wait, hours=4.0)
        _add_status_change(
            j_wait, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 6))
        )

        # Direct
        j_dir = _make_job(
            name="Dir", company=acme, created_dt=_nz_dt(date(2026, 3, 5)), staff=staff
        )
        _attach_estimate(j_dir, hours=8.0)
        _add_status_change(j_dir, old="draft", new="approved", at=_nz_dt(date(2026, 3, 7)))

        # Still draft
        j_draft = _make_job(
            name="Drf", company=acme, created_dt=_nz_dt(date(2026, 3, 6)), staff=staff
        )
        _attach_estimate(j_draft, hours=16.0)

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        f = rep["conversion_funnel"]
        assert f["accepted"]["count"] == 1
        assert f["accepted"]["hours"] == pytest.approx(1.0)
        assert f["rejected"]["count"] == 1
        assert f["rejected"]["hours"] == pytest.approx(2.0)
        assert f["waiting"]["count"] == 1
        assert f["waiting"]["hours"] == pytest.approx(4.0)
        assert f["direct"]["count"] == 1
        assert f["direct"]["hours"] == pytest.approx(8.0)
        assert f["still_draft"]["count"] == 1
        assert f["still_draft"]["hours"] == pytest.approx(16.0)

        # Mutual exclusivity check
        total = sum(f[k]["count"] for k in f)
        assert total == 5

    def test_missing_creation_anchor_excludes_and_warns(self, acme: Company, staff: Staff) -> None:
        """A job with events in the reporting period but no usable
        job_created anchor must produce a funnel warning rather than
        being silently dropped.
        """
        job = _make_job(
            name="FunnelAnchorless", company=acme, created_dt=_nz_dt(date(2026, 3, 5)), staff=staff
        )
        _attach_quote(job, hours=3.0)
        JobEvent.objects.filter(job=job, event_type="job_created").delete()
        _add_status_change(job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 10)))

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        # All five funnel buckets should be zero — this job can't be placed.
        f = rep["conversion_funnel"]
        assert sum(f[k]["count"] for k in f) == 0
        codes = {(w["code"], w["section"]) for w in rep["warnings"]}
        assert ("missing_creation_anchor", "conversion_funnel") in codes


class TestTrend:
    # v1's setUp built the client company and an 8h/day target for every test.
    pytestmark = pytest.mark.usefixtures("eight_hour_target")

    def test_rolling_average_derived_from_weekly_series(self, acme: Company, staff: Staff) -> None:
        """Build approvals across three weeks; verify the rolling average for the
        last week equals the mean of the underlying weekly series.
        """
        end_date = date(2026, 3, 22)  # Sunday — last week ends here

        # Three approvals, one per week, at 6h, 12h, 18h
        weekly_hours = [6.0, 12.0, 18.0]
        for i, hours in enumerate(weekly_hours):
            approved_day = end_date - timedelta(weeks=2 - i, days=2)  # Friday-ish
            j = _make_job(
                name=f"T{i}",
                company=acme,
                created_dt=_nz_dt(approved_day - timedelta(days=10)),
                staff=staff,
            )
            _attach_quote(j, hours=hours)
            _add_status_change(
                j,
                old="draft",
                new="awaiting_approval",
                at=_nz_dt(approved_day - timedelta(days=2)),
            )
            _add_status_change(j, old="awaiting_approval", new="approved", at=_nz_dt(approved_day))

        rep = SalesPipelineService.get_report(
            date(2026, 3, 1), end_date, rolling_window_weeks=3, trend_weeks=3
        )
        weeks = rep["trend"]["weeks"]
        rolling = rep["trend"]["rolling_average"]
        assert len(weeks) == 3
        assert len(rolling) == 3

        approved_series = [w["approved_hours"] for w in weeks]
        # Last rolling avg should equal the mean of the full window (3 weeks).
        assert rolling[-1]["rolling_avg_approved_hours"] == pytest.approx(
            sum(approved_series) / 3.0
        )

    def test_working_days_match_existing_logic(self) -> None:
        # 2026-03-02 (Mon) to 2026-03-06 (Fri) = 5 weekdays, no NZ holidays
        rep = SalesPipelineService.get_report(date(2026, 3, 2), date(2026, 3, 6), 4, 13)
        assert rep["scoreboard"]["working_days"] == 5


class TestPeriodDefault:
    # The service reads the CompanyDefaults singleton even with no jobs.
    pytestmark = pytest.mark.usefixtures("defaults")

    def test_no_explicit_dates_reasonable(self) -> None:
        # Even with no jobs, the report should produce a coherent shape
        rep = SalesPipelineService.get_report(date(2026, 1, 1), timezone.localdate(), 4, 13)
        assert "scoreboard" in rep
        assert "pipeline_snapshot" in rep
        assert "velocity" in rep
        assert "conversion_funnel" in rep
        assert "trend" in rep
        assert rep["scoreboard"]["approved_jobs_count"] == 0
