"""Service-level tests for the Sales Pipeline Report.

Covers every bullet from the requirements plan
``docs/plans/2026-04-16-sales-pipeline-report.md`` "Service-level tests"
section. Builds JobEvent fixtures directly so that historical timestamps
and ``delta_after`` values can be controlled precisely.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.services import SalesPipelineService
from apps.client.models import Client
from apps.job.models import Job, JobEvent
from apps.job.models.costing import CostSet
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults, XeroPayItem

NZ_TZ = ZoneInfo("Pacific/Auckland")


def _nz_dt(d: date, hour: int = 12) -> datetime:
    """Build an NZ-local datetime at the given hour (default noon)."""
    return datetime.combine(d, time(hour=hour), tzinfo=NZ_TZ)


class SalesPipelineServiceFixturesMixin:
    """Shared fixture-builders. Use via multiple inheritance with BaseTestCase."""

    def _make_client(self, name: str = "Acme Co") -> Client:
        return Client.objects.create(
            name=name,
            email=f"{name.lower().replace(' ', '_')}@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

    def _make_job(self, *, name: str, client: Client, created_dt: datetime) -> Job:
        """Create a job with a deterministic ``job_created`` event at ``created_dt``.

        ``Job.save()`` itself does not emit ``job_created`` — that lives in
        ``JobRestService.create_job``. The test fixture bypasses the REST
        service, so we emit the event explicitly at the requested timestamp.
        """
        pay_item = XeroPayItem.get_ordinary_time()
        job = Job(
            name=name,
            client=client,
            created_by=self.test_staff,
            default_xero_pay_item=pay_item,
        )
        job.save(staff=self.test_staff)
        JobEvent.objects.create(
            job=job,
            event_type="job_created",
            timestamp=created_dt,
            staff=self.test_staff,
            detail={
                "job_name": job.name,
                "client_name": client.name if client else "Shop Job",
                "contact_name": None,
                "initial_status": job.get_status_display(),
                "pricing_methodology": job.get_pricing_methodology_display(),
            },
            delta_after={"status": job.status},
        )
        return job

    def _add_status_change(
        self,
        job: Job,
        *,
        old: str,
        new: str,
        at: datetime,
        event_type: str = "status_changed",
    ) -> JobEvent:
        return JobEvent.objects.create(
            job=job,
            staff=self.test_staff,
            event_type=event_type,
            timestamp=at,
            delta_before={"status": old},
            delta_after={"status": new},
        )

    def _add_quote_accepted(
        self, job: Job, *, at: datetime, old_status: str = "awaiting_approval"
    ) -> JobEvent:
        return JobEvent.objects.create(
            job=job,
            staff=self.test_staff,
            event_type="quote_accepted",
            timestamp=at,
            delta_before={"status": old_status},
            delta_after={"status": "approved"},
        )

    def _add_job_rejected(self, job: Job, *, at: datetime) -> JobEvent:
        return JobEvent.objects.create(
            job=job,
            staff=self.test_staff,
            event_type="job_rejected",
            timestamp=at,
            delta_before={"status": "awaiting_approval", "rejected_flag": False},
            delta_after={"status": "archived", "rejected_flag": True},
        )

    def _attach_quote(self, job: Job, *, hours: float, rev: float = 0.0) -> CostSet:
        # Job.save() already seeds a rev=1 quote CostSet; update it in place so
        # we don't trip the (job, kind, rev) unique constraint.
        cs = job.latest_quote
        cs.summary = {"cost": 0.0, "rev": rev, "hours": hours}
        cs.save(update_fields=["summary"])
        return cs

    def _attach_estimate(self, job: Job, *, hours: float, rev: float = 0.0) -> CostSet:
        cs = job.latest_estimate
        cs.summary = {"cost": 0.0, "rev": rev, "hours": hours}
        cs.save(update_fields=["summary"])
        return cs

    def _detach_summaries(self, job: Job) -> None:
        """Simulate a job with no usable quote/estimate hours summary."""
        job.latest_quote = None
        job.latest_estimate = None
        job.save(
            staff=self.test_staff,
            update_fields=["latest_quote", "latest_estimate", "updated_at"],
        )


class ScoreboardTests(SalesPipelineServiceFixturesMixin, BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client_obj = self._make_client()
        defaults = CompanyDefaults.get_solo()
        defaults.daily_approved_hours_target = Decimal("8.00")
        defaults.save()
        self.start = date(2026, 3, 2)  # Monday
        self.end = date(2026, 3, 6)  # Friday — 5 working days

    def test_status_changed_into_approved_counts(self):
        job = self._make_job(
            name="J1", client=self.client_obj, created_dt=_nz_dt(date(2026, 1, 5))
        )
        self._attach_quote(job, hours=12.5)
        self._add_status_change(
            job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10))
        )
        self._add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 3, 4))
        )

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        self.assertEqual(rep["scoreboard"]["approved_jobs_count"], 1)
        self.assertAlmostEqual(rep["scoreboard"]["approved_hours_total"], 12.5)
        # Not direct — went through awaiting_approval.
        self.assertEqual(rep["scoreboard"]["direct_jobs_count"], 0)

    def test_quote_accepted_counts(self):
        job = self._make_job(
            name="J2", client=self.client_obj, created_dt=_nz_dt(date(2026, 1, 5))
        )
        self._attach_quote(job, hours=4.0)
        self._add_status_change(
            job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10))
        )
        self._add_quote_accepted(job, at=_nz_dt(date(2026, 3, 5)))

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        self.assertEqual(rep["scoreboard"]["approved_jobs_count"], 1)
        self.assertAlmostEqual(rep["scoreboard"]["approved_hours_total"], 4.0)

    def test_direct_approved_counts_in_direct_bucket(self):
        job = self._make_job(
            name="J3", client=self.client_obj, created_dt=_nz_dt(date(2026, 1, 5))
        )
        self._attach_quote(job, hours=6.0)
        # Straight from draft to approved — no awaiting and no quote_accepted.
        self._add_status_change(
            job, old="draft", new="approved", at=_nz_dt(date(2026, 3, 4))
        )

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        self.assertEqual(rep["scoreboard"]["approved_jobs_count"], 1)
        self.assertEqual(rep["scoreboard"]["direct_jobs_count"], 1)
        self.assertAlmostEqual(rep["scoreboard"]["direct_hours"], 6.0)

    def test_dedupe_approved_then_in_progress_same_period(self):
        job = self._make_job(
            name="J4", client=self.client_obj, created_dt=_nz_dt(date(2026, 1, 5))
        )
        self._attach_quote(job, hours=10.0)
        self._add_status_change(
            job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10))
        )
        self._add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 3, 3))
        )
        self._add_status_change(
            job, old="approved", new="in_progress", at=_nz_dt(date(2026, 3, 5))
        )

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        self.assertEqual(rep["scoreboard"]["approved_jobs_count"], 1)
        self.assertAlmostEqual(rep["scoreboard"]["approved_hours_total"], 10.0)

    def test_target_reflects_company_defaults(self):
        defaults = CompanyDefaults.get_solo()
        defaults.daily_approved_hours_target = Decimal("20.00")
        defaults.save()

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        # 5 NZ working days × 20 = 100
        self.assertEqual(rep["scoreboard"]["working_days"], 5)
        self.assertAlmostEqual(rep["scoreboard"]["target_hours_for_period"], 100.0)
        self.assertAlmostEqual(rep["period"]["daily_approved_hours_target"], 20.0)

    def test_missing_hours_summary_excludes_and_warns(self):
        job = self._make_job(
            name="No hours", client=self.client_obj, created_dt=_nz_dt(date(2026, 1, 5))
        )
        # Detach the default quote/estimate cost sets so hours resolution
        # genuinely fails (Job.save() seeds both with hours=0.0 otherwise).
        self._detach_summaries(job)
        self._add_status_change(
            job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10))
        )
        self._add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 3, 4))
        )

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        self.assertEqual(rep["scoreboard"]["approved_jobs_count"], 0)
        codes = {(w["code"], w["section"]) for w in rep["warnings"]}
        self.assertIn(("missing_hours_summary", "scoreboard"), codes)


class SnapshotTests(SalesPipelineServiceFixturesMixin, BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client_obj = self._make_client()

    def test_replays_to_historical_status_not_live(self):
        # Created in draft 2026-01-05, moved to awaiting_approval 2026-02-01,
        # approved 2026-03-15, archived 2026-04-10. As of end_date 2026-02-15
        # the historical state is "awaiting_approval".
        job = self._make_job(
            name="Replay job",
            client=self.client_obj,
            created_dt=_nz_dt(date(2026, 1, 5)),
        )
        self._attach_quote(job, hours=7.0, rev=2100.0)
        self._add_status_change(
            job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 1))
        )
        self._add_status_change(
            job, old="awaiting_approval", new="approved", at=_nz_dt(date(2026, 3, 15))
        )
        self._add_status_change(
            job, old="approved", new="archived", at=_nz_dt(date(2026, 4, 10))
        )

        # Live job.status reflects the most recent change (archived) — service
        # must use the replay, not job.status.
        job.refresh_from_db()
        self.assertNotEqual(job.status, "awaiting_approval")

        rep = SalesPipelineService.get_report(
            date(2026, 1, 1), date(2026, 2, 15), 4, 13
        )
        self.assertEqual(rep["pipeline_snapshot"]["awaiting_approval"]["count"], 1)
        self.assertAlmostEqual(
            rep["pipeline_snapshot"]["awaiting_approval"]["hours_total"], 7.0
        )

    def test_days_in_stage_uses_most_recent_entry(self):
        end_date = date(2026, 3, 20)
        # Created in awaiting_approval, bounced back to draft, then back to
        # awaiting_approval. Days-in-stage measured from the latest entry.
        job = self._make_job(
            name="Bouncy", client=self.client_obj, created_dt=_nz_dt(date(2026, 1, 1))
        )
        # Override creation status to awaiting_approval for this test so the
        # historical replay anchor starts there.
        JobEvent.objects.filter(job=job, event_type="job_created").update(
            delta_after={"status": "awaiting_approval"}
        )
        self.assertEqual(
            JobEvent.objects.filter(job=job, event_type="job_created").count(),
            1,
        )
        self._attach_quote(job, hours=3.0)
        self._add_status_change(
            job, old="awaiting_approval", new="draft", at=_nz_dt(date(2026, 2, 1))
        )
        self._add_status_change(
            job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 10))
        )

        rep = SalesPipelineService.get_report(date(2026, 1, 1), end_date, 4, 13)
        bucket = rep["pipeline_snapshot"]["awaiting_approval"]
        self.assertEqual(bucket["count"], 1)
        self.assertEqual(bucket["jobs"][0]["days_in_stage"], 10)

    def test_draft_uses_estimate_summary_awaiting_uses_quote(self):
        d_job = self._make_job(
            name="DraftJ", client=self.client_obj, created_dt=_nz_dt(date(2026, 2, 1))
        )
        self._attach_estimate(d_job, hours=2.5)
        # Quote also exists but draft must use estimate
        self._attach_quote(d_job, hours=99.9)

        a_job = self._make_job(
            name="AwaitJ", client=self.client_obj, created_dt=_nz_dt(date(2026, 2, 1))
        )
        self._attach_estimate(a_job, hours=99.9)
        self._attach_quote(a_job, hours=4.5)
        self._add_status_change(
            a_job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 5))
        )

        rep = SalesPipelineService.get_report(
            date(2026, 1, 1), date(2026, 2, 28), 4, 13
        )
        self.assertAlmostEqual(rep["pipeline_snapshot"]["draft"]["hours_total"], 2.5)
        self.assertAlmostEqual(
            rep["pipeline_snapshot"]["awaiting_approval"]["hours_total"], 4.5
        )

    def test_narrowed_fetch_preserves_historical_replay(self):
        """A job created long before the reporting window whose transitions
        leave it in a pipeline stage at ``end_date`` must still surface in
        the snapshot. Tier 1 narrows the fetch window to save work, so this
        guards against regressing historical replay for those jobs.

        See ``docs/plans/now-the-performance-concerns-stateful-taco.md``.
        """
        job = self._make_job(
            name="LongHistory",
            client=self.client_obj,
            created_dt=_nz_dt(date(2023, 1, 15)),
        )
        self._attach_quote(job, hours=9.0, rev=1800.0)
        # Transition to awaiting_approval three years before the window.
        self._add_status_change(
            job,
            old="draft",
            new="awaiting_approval",
            at=_nz_dt(date(2023, 6, 20)),
        )
        # Nothing else happens. Historical state as of 2026-04-30 must still
        # be awaiting_approval, derivable only by fetching the 2023 event.
        start = date(2026, 4, 1)
        end = date(2026, 4, 30)

        rep = SalesPipelineService.get_report(start, end, 4, 4)
        bucket = rep["pipeline_snapshot"]["awaiting_approval"]
        self.assertEqual(bucket["count"], 1)
        self.assertAlmostEqual(bucket["hours_total"], 9.0)

    def test_narrowed_fetch_applies_lower_bound_for_in_window_query(self):
        """The main events query must carry a ``timestamp >=`` filter so we
        aren't hauling years of history for a short report window. The
        pre-window query that backfills pipeline-stage jobs is allowed to
        run unbounded below."""
        # A job entirely outside the reporting window. With narrowing, its
        # events should arrive via the pipeline-stage pre-window backfill
        # (single queryset), not the in-window queryset.
        outside_job = self._make_job(
            name="Outside",
            client=self.client_obj,
            created_dt=_nz_dt(date(2022, 3, 1)),
        )
        self._attach_estimate(outside_job, hours=2.0)
        self._add_status_change(
            outside_job,
            old="draft",
            new="awaiting_approval",
            at=_nz_dt(date(2022, 8, 1)),
        )
        self._add_status_change(
            outside_job,
            old="awaiting_approval",
            new="archived",
            at=_nz_dt(date(2022, 12, 1)),
        )

        start = date(2026, 4, 1)
        end = date(2026, 4, 30)

        with CaptureQueriesContext(connection) as ctx:
            SalesPipelineService.get_report(start, end, 4, 4)

        jobevent_selects = [
            q["sql"]
            for q in ctx.captured_queries
            if '"job_jobevent"' in q["sql"]
            and q["sql"].lstrip().upper().startswith("SELECT")
        ]
        self.assertTrue(jobevent_selects, "expected JobEvent SELECTs")
        has_lower_bound = any('"timestamp" >=' in q for q in jobevent_selects)
        self.assertTrue(
            has_lower_bound,
            "no JobEvent SELECT carried a timestamp >= lower bound — "
            "fetch narrowing regressed. Queries:\n" + "\n".join(jobevent_selects),
        )

    def test_missing_creation_anchor_excludes_and_warns(self):
        # Build a job and then delete its job_created event.
        job = self._make_job(
            name="Anchorless",
            client=self.client_obj,
            created_dt=_nz_dt(date(2026, 2, 1)),
        )
        self._attach_quote(job, hours=5.0)
        JobEvent.objects.filter(job=job, event_type="job_created").delete()
        # Add a status change so the job has events at all
        self._add_status_change(
            job, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 2, 10))
        )

        rep = SalesPipelineService.get_report(
            date(2026, 1, 1), date(2026, 2, 28), 4, 13
        )
        self.assertEqual(rep["pipeline_snapshot"]["awaiting_approval"]["count"], 0)
        codes = {(w["code"], w["section"]) for w in rep["warnings"]}
        self.assertIn(("missing_creation_anchor", "pipeline_snapshot"), codes)


class VelocityTests(SalesPipelineServiceFixturesMixin, BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client_obj = self._make_client()

    def test_median_p80_sample_size(self):
        """Three approvals in period with created→approved deltas of 5, 10, 20 days."""
        for i, gap in enumerate((5, 10, 20)):
            created = date(2026, 2, 1)
            approved_dt = _nz_dt(date(2026, 2, 1) + timedelta(days=gap))
            j = self._make_job(
                name=f"V{i}", client=self.client_obj, created_dt=_nz_dt(created)
            )
            self._attach_quote(j, hours=1.0)
            self._add_status_change(
                j,
                old="draft",
                new="awaiting_approval",
                at=_nz_dt(date(2026, 2, 1) + timedelta(days=1)),
            )
            self._add_status_change(
                j, old="awaiting_approval", new="approved", at=approved_dt
            )

        rep = SalesPipelineService.get_report(
            date(2026, 2, 1), date(2026, 2, 28), 4, 13
        )
        v = rep["velocity"]["created_to_approved"]
        self.assertEqual(v["sample_size"], 3)
        self.assertAlmostEqual(v["median_days"], 10.0)
        # p80 over [5, 10, 20] (n=3, idx round(0.8*2)=2) = 20
        self.assertAlmostEqual(v["p80_days"], 20.0)

    def test_missing_creation_anchor_excludes_and_warns(self):
        """A velocity-relevant event in-period on a job missing its
        job_created anchor must produce a warning, not silent exclusion."""
        job = self._make_job(
            name="VelAnchorless",
            client=self.client_obj,
            created_dt=_nz_dt(date(2026, 2, 1)),
        )
        self._attach_quote(job, hours=1.0)
        JobEvent.objects.filter(job=job, event_type="job_created").delete()
        self._add_status_change(
            job,
            old="draft",
            new="awaiting_approval",
            at=_nz_dt(date(2026, 2, 5)),
        )
        self._add_status_change(
            job,
            old="awaiting_approval",
            new="approved",
            at=_nz_dt(date(2026, 2, 10)),
        )

        rep = SalesPipelineService.get_report(
            date(2026, 2, 1), date(2026, 2, 28), 4, 13
        )
        self.assertEqual(rep["velocity"]["created_to_approved"]["sample_size"], 0)
        codes = {(w["code"], w["section"]) for w in rep["warnings"]}
        self.assertIn(("missing_creation_anchor", "velocity"), codes)


class FunnelTests(SalesPipelineServiceFixturesMixin, BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client_obj = self._make_client()
        self.start = date(2026, 3, 1)
        self.end = date(2026, 3, 31)

    def test_categorization_is_mutually_exclusive(self):
        # Accepted via quote_accepted
        j_acc = self._make_job(
            name="Acc", client=self.client_obj, created_dt=_nz_dt(date(2026, 3, 2))
        )
        self._attach_quote(j_acc, hours=1.0)
        self._add_status_change(
            j_acc, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 5))
        )
        self._add_quote_accepted(j_acc, at=_nz_dt(date(2026, 3, 10)))

        # Rejected
        j_rej = self._make_job(
            name="Rej", client=self.client_obj, created_dt=_nz_dt(date(2026, 3, 3))
        )
        self._attach_quote(j_rej, hours=2.0)
        self._add_status_change(
            j_rej, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 6))
        )
        self._add_job_rejected(j_rej, at=_nz_dt(date(2026, 3, 15)))

        # Waiting
        j_wait = self._make_job(
            name="Wait", client=self.client_obj, created_dt=_nz_dt(date(2026, 3, 4))
        )
        self._attach_quote(j_wait, hours=4.0)
        self._add_status_change(
            j_wait, old="draft", new="awaiting_approval", at=_nz_dt(date(2026, 3, 6))
        )

        # Direct
        j_dir = self._make_job(
            name="Dir", client=self.client_obj, created_dt=_nz_dt(date(2026, 3, 5))
        )
        self._attach_estimate(j_dir, hours=8.0)
        self._add_status_change(
            j_dir, old="draft", new="approved", at=_nz_dt(date(2026, 3, 7))
        )

        # Still draft
        j_draft = self._make_job(
            name="Drf", client=self.client_obj, created_dt=_nz_dt(date(2026, 3, 6))
        )
        self._attach_estimate(j_draft, hours=16.0)

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        f = rep["conversion_funnel"]
        self.assertEqual(f["accepted"]["count"], 1)
        self.assertAlmostEqual(f["accepted"]["hours"], 1.0)
        self.assertEqual(f["rejected"]["count"], 1)
        self.assertAlmostEqual(f["rejected"]["hours"], 2.0)
        self.assertEqual(f["waiting"]["count"], 1)
        self.assertAlmostEqual(f["waiting"]["hours"], 4.0)
        self.assertEqual(f["direct"]["count"], 1)
        self.assertAlmostEqual(f["direct"]["hours"], 8.0)
        self.assertEqual(f["still_draft"]["count"], 1)
        self.assertAlmostEqual(f["still_draft"]["hours"], 16.0)

        # Mutual exclusivity check
        total = sum(f[k]["count"] for k in f)
        self.assertEqual(total, 5)

    def test_missing_creation_anchor_excludes_and_warns(self):
        """A job with events in the reporting period but no usable
        job_created anchor must produce a funnel warning rather than
        being silently dropped."""
        job = self._make_job(
            name="FunnelAnchorless",
            client=self.client_obj,
            created_dt=_nz_dt(date(2026, 3, 5)),
        )
        self._attach_quote(job, hours=3.0)
        JobEvent.objects.filter(job=job, event_type="job_created").delete()
        self._add_status_change(
            job,
            old="draft",
            new="awaiting_approval",
            at=_nz_dt(date(2026, 3, 10)),
        )

        rep = SalesPipelineService.get_report(self.start, self.end, 4, 13)
        # All five funnel buckets should be zero — this job can't be placed.
        f = rep["conversion_funnel"]
        self.assertEqual(sum(f[k]["count"] for k in f), 0)
        codes = {(w["code"], w["section"]) for w in rep["warnings"]}
        self.assertIn(("missing_creation_anchor", "conversion_funnel"), codes)


class TrendTests(SalesPipelineServiceFixturesMixin, BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client_obj = self._make_client()
        defaults = CompanyDefaults.get_solo()
        defaults.daily_approved_hours_target = Decimal("8.00")
        defaults.save()

    def test_rolling_average_derived_from_weekly_series(self):
        """Build approvals across three weeks; verify the rolling average for the
        last week equals the mean of the underlying weekly series."""
        end_date = date(2026, 3, 22)  # Sunday — last week ends here

        # Three approvals, one per week, at 6h, 12h, 18h
        weekly_hours = [6.0, 12.0, 18.0]
        for i, hours in enumerate(weekly_hours):
            approved_day = end_date - timedelta(weeks=2 - i, days=2)  # Friday-ish
            j = self._make_job(
                name=f"T{i}",
                client=self.client_obj,
                created_dt=_nz_dt(approved_day - timedelta(days=10)),
            )
            self._attach_quote(j, hours=hours)
            self._add_status_change(
                j,
                old="draft",
                new="awaiting_approval",
                at=_nz_dt(approved_day - timedelta(days=2)),
            )
            self._add_status_change(
                j, old="awaiting_approval", new="approved", at=_nz_dt(approved_day)
            )

        rep = SalesPipelineService.get_report(
            date(2026, 3, 1), end_date, rolling_window_weeks=3, trend_weeks=3
        )
        weeks = rep["trend"]["weeks"]
        rolling = rep["trend"]["rolling_average"]
        self.assertEqual(len(weeks), 3)
        self.assertEqual(len(rolling), 3)

        approved_series = [w["approved_hours"] for w in weeks]
        # Last rolling avg should equal the mean of the full window (3 weeks).
        self.assertAlmostEqual(
            rolling[-1]["rolling_avg_approved_hours"],
            sum(approved_series) / 3.0,
        )

    def test_working_days_match_existing_logic(self):
        # 2026-03-02 (Mon) to 2026-03-06 (Fri) = 5 weekdays, no NZ holidays
        rep = SalesPipelineService.get_report(date(2026, 3, 2), date(2026, 3, 6), 4, 13)
        self.assertEqual(rep["scoreboard"]["working_days"], 5)


class PeriodDefaultTests(SalesPipelineServiceFixturesMixin, BaseTestCase):
    def test_no_explicit_dates_reasonable(self):
        # Even with no jobs, the report should produce a coherent shape
        rep = SalesPipelineService.get_report(
            date(2026, 1, 1), timezone.localdate(), 4, 13
        )
        self.assertIn("scoreboard", rep)
        self.assertIn("pipeline_snapshot", rep)
        self.assertIn("velocity", rep)
        self.assertIn("conversion_funnel", rep)
        self.assertIn("trend", rep)
        self.assertEqual(rep["scoreboard"]["approved_jobs_count"], 0)
