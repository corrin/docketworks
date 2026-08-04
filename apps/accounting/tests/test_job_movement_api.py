"""Business-behaviour tests for GET /api/accounting/reports/job-movement/.

v1 shipped this 611-line view entirely untested; these are its first tests.
The v1 boundary quirk is pinned deliberately: both dates parse as local
MIDNIGHT, so events on the end date itself fall outside `timestamp <= end`.
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.job.models.job_event import JobEvent

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

URL = "/api/accounting/reports/job-movement/"


def move_status(job: Job, staff: Staff, *, old: str, new: str, days_ago: int) -> JobEvent:
    event = JobEvent.objects.create(
        job=job,
        staff=staff,
        event_type="status_changed",
        timestamp=timezone.now() - timedelta(days=days_ago),
        delta_before={"status": old},
        delta_after={"status": new},
    )
    Job.objects.filter(pk=job.pk).untracked_update(status=new)
    job.refresh_from_db()
    return event


def week_params(**extra: str) -> dict[str, str]:
    today = timezone.localdate()
    return {
        "start_date": (today - timedelta(days=7)).isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
        **extra,
    }


class TestJobMovement:
    def test_requires_authentication(self) -> None:
        assert Client().get(URL, week_params()).status_code == 401

    def test_missing_dates_are_rejected(self, authenticated_client: Client) -> None:
        assert authenticated_client.get(URL).status_code == 422

    def test_counts_quotes_and_conversions(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Movement Co")
        won = make_job(company, staff, name="Won job")
        move_status(won, staff, old="draft", new="awaiting_approval", days_ago=3)
        move_status(won, staff, old="awaiting_approval", new="approved", days_ago=2)

        still_draft = make_job(company, staff, name="Still draft")

        rejected = make_job(company, staff, name="Rejected job")
        Job.objects.filter(pk=rejected.pk).untracked_update(rejected_flag=True, status="archived")

        body = authenticated_client.get(URL, week_params()).json()
        metrics = body["metrics"]
        assert metrics["draft_jobs_created"]["count"] == 3
        assert metrics["quotes_submitted"]["count"] == 1
        assert metrics["quotes_accepted"]["count"] == 1
        assert metrics["quote_acceptance_rate"]["rate"] == 100.0
        assert metrics["jobs_won"]["count"] == 1  # won only; rejected excluded
        assert metrics["jobs_won"]["still_draft"] == 1
        assert metrics["jobs_won"]["rejected"] == 1
        assert metrics["jobs_won"]["total_created"] == 3
        assert metrics["draft_conversion_rate"]["rate"] == pytest.approx(100 / 3)
        paths = metrics["workflow_paths"]
        assert paths["through_quotes"] == 1
        # The rejected job left draft without a quote event, so it counts as
        # skip_quotes (v1 semantics: any non-draft job without a quote event).
        assert paths["skip_quotes"] == 1
        assert paths["quote_usage_percent"] == 50.0
        assert body["period"]["days"] == 9
        assert "comparison_period" not in body
        assert still_draft.status == "draft"

    def test_comparison_period_adds_change_metrics(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Compare Co")
        current = make_job(company, staff, name="Current job")
        old = make_job(company, staff, name="Old job")
        two_weeks_ago = timezone.now() - timedelta(days=14)
        Job.objects.filter(pk=old.pk).untracked_update(created_at=two_weeks_ago)

        today = timezone.localdate()
        params = week_params(
            compare_start_date=(today - timedelta(days=16)).isoformat(),
            compare_end_date=(today - timedelta(days=8)).isoformat(),
        )
        body = authenticated_client.get(URL, params).json()
        draft_metric = body["metrics"]["draft_jobs_created"]
        assert draft_metric["count"] == 1
        assert draft_metric["comparison_value"] == 1
        assert draft_metric["change"] == 0
        assert draft_metric["change_percent"] == 0.0
        assert body["comparison_period"]["days"] == 9
        assert current.pk is not None

    def test_details_and_baseline_sections_are_optional(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Detail Co")
        job = make_job(company, staff, name="Listed job")

        base = authenticated_client.get(URL, week_params()).json()
        assert "details" not in base
        assert "baseline" not in base

        body = authenticated_client.get(
            URL, week_params(include_details="true", baseline_days="70")
        ).json()
        detail_jobs = {j["id"] for j in body["details"]["draft_jobs"]}
        assert str(job.id) in detail_jobs
        assert body["baseline"]["period_days"] == 70
        assert body["baseline"]["weeks"] == 10.0
        assert body["baseline"]["weekly_averages"]["draft_jobs_created"] == 0.1
