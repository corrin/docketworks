"""Business-behaviour tests for GET /api/accounting/reports/job-aging/.

Ported intent from v1 (which had no direct tests for this endpoint): the
report's value is the three financial totals per job, archived-job filtering,
and recency ordering — each is asserted against data a regression would
plausibly corrupt (ADR 0025).
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job, make_material_line
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.models.job_event import JobEvent
from apps.timesheet.tests.conftest import make_time_line

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

URL = "/api/accounting/reports/job-aging/"


def add_line(job: Job, set_kind: str, *, rev: str) -> object:
    """One material line on the given cost set — total_rev drives the report."""
    return make_material_line(job, set_kind=set_kind, rev=rev)


class TestJobAging:
    def test_requires_authentication(self) -> None:
        assert Client().get(URL).status_code == 401

    def test_financial_totals_come_from_each_cost_set(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Aging Co")
        job = make_job(company, staff)
        add_line(job, "estimate", rev="100.00")
        add_line(job, "quote", rev="150.00")
        add_line(job, "actual", rev="90.00")

        response = authenticated_client.get(URL)
        assert response.status_code == 200
        jobs = response.json()["jobs"]
        row = next(j for j in jobs if j["id"] == str(job.id))
        assert row["financial_data"] == {
            "estimate_total": 100.0,
            "quote_total": 150.0,
            "actual_total": 90.0,
        }
        assert row["job_number"] == job.job_number
        assert row["company_name"] == "Aging Co"
        assert row["status_display"] == job.get_status_display()

    def test_archived_jobs_are_excluded_unless_requested(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Archive Co")
        live = make_job(company, staff, name="Live job")
        archived = make_job(company, staff, name="Archived job")
        archived.status = "archived"
        archived.save(staff=staff)

        default_ids = {j["id"] for j in authenticated_client.get(URL).json()["jobs"]}
        assert str(live.id) in default_ids
        assert str(archived.id) not in default_ids

        with_archived = authenticated_client.get(URL, {"include_archived": "true"})
        ids = {j["id"] for j in with_archived.json()["jobs"]}
        assert {str(live.id), str(archived.id)} <= ids

    def test_jobs_sorted_by_most_recent_activity_first(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Sort Co")
        stale = make_job(company, staff, name="Stale job")
        fresh = make_job(company, staff, name="Fresh job")
        # Activity recency comes from cost-line accounting dates (among other
        # sources); Job.save() itself just made both jobs "updated today", so
        # push the stale job's updated_at into the past to separate them.
        week_ago = timezone.now() - timedelta(days=7)
        Job.objects.filter(pk=stale.pk).update(updated_at=week_ago)
        JobEvent.objects.filter(job=stale).update(timestamp=week_ago)
        Job.objects.filter(pk=fresh.pk).update(updated_at=timezone.now())

        jobs = authenticated_client.get(URL).json()["jobs"]
        positions = {j["id"]: i for i, j in enumerate(jobs)}
        assert positions[str(fresh.id)] < positions[str(stale.id)]
        fresh_row = jobs[positions[str(fresh.id)]]
        assert fresh_row["timing_data"]["last_activity_days_ago"] == 0

    def test_corrupt_staff_reference_degrades_the_job_not_the_report(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        """v1 kept a job whose time line had a dangling staff ref, with null
        last-activity fields (the scan aborted); v2 matches — the job must NOT
        drop out of the report, and the rest still sorts."""
        company = make_company("Corrupt Co")
        healthy = make_job(company, staff, name="Healthy job")
        corrupt = make_job(company, staff, name="Corrupt job")
        line = make_time_line(corrupt, staff, accounting_date=timezone.localdate())
        # Model validation forbids writing this state, but a v1 restore can
        # carry it — inject below the save() layer (entry_seq cleared too, to
        # satisfy the staff/entry_seq pairing check constraint).
        CostLine.objects.filter(pk=line.pk).update(staff=None, entry_seq=None)

        jobs = authenticated_client.get(URL).json()["jobs"]
        by_id = {j["id"]: j for j in jobs}
        assert str(corrupt.id) in by_id
        corrupt_row = by_id[str(corrupt.id)]
        assert corrupt_row["timing_data"]["last_activity_date"] is None
        assert corrupt_row["timing_data"]["last_activity_type"] is None
        # Jobs with no resolvable activity sort after jobs with activity.
        positions = {j["id"]: i for i, j in enumerate(jobs)}
        assert positions[str(healthy.id)] < positions[str(corrupt.id)]

    def test_days_in_current_status_uses_latest_status_change_event(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Status Co")
        job = make_job(company, staff)
        # v1 filtered on event_type="status_change", a value nothing ever
        # writes (the tracker emits "status_changed"), so v1's
        # days_in_current_status silently always fell back to the creation
        # date. v2 filters on the real event type — v1 defect, ledgered.
        JobEvent.objects.create(
            job=job,
            staff=staff,
            event_type="status_changed",
            timestamp=timezone.now() - timedelta(days=10),
            detail={"old": "draft", "new": "in_progress"},
        )

        jobs = authenticated_client.get(URL).json()["jobs"]
        row = next(j for j in jobs if j["id"] == str(job.id))
        assert row["timing_data"]["days_in_current_status"] == 10
