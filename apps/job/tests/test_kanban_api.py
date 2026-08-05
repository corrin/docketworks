"""API tests for the kanban endpoints.

Guards the wire contract: fetch-all/fetch-by-column/fetch-by-status shapes,
status-values, update-status and reorder validation, the incremental
kanban-changes feed, and staff assignment.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db.models import Count, Max
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job, seed_job_prereqs
from apps.core.models import AppError
from apps.job.kanban_version import KanbanDatasetVersion
from apps.job.models import Job

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.job.tests.urls"),
]


def _make_status_job(company: Company, staff: Staff, name: str, status: str) -> Job:
    seed_job_prereqs()
    job = Job(name=name, company=company, status=status)
    job.save(staff=staff)
    return job


def _current_kanban_version() -> str:
    """Encode the Job dataset version for the kanban change-feed contract."""
    aggregates = Job.objects.aggregate(
        count=Count("id"),
        latest_created=Max("created_at"),
        latest_updated=Max("updated_at"),
    )
    return KanbanDatasetVersion.from_values(
        updated_at=aggregates["latest_updated"],
        created_at=aggregates["latest_created"],
        count=aggregates["count"],
    ).encode()


class TestFetchEndpoints:
    def test_fetch_all_returns_active_and_archived(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        active = _make_status_job(company, office_staff, "Active Job", "in_progress")
        archived = _make_status_job(company, office_staff, "Archived Job", "archived")
        _make_status_job(company, office_staff, "Special Job", "special")

        response = client.get("/api/job/jobs/fetch-all/")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert [job["id"] for job in payload["active_jobs"]] == [str(active.id)]
        assert [job["id"] for job in payload["archived_jobs"]] == [str(archived.id)]
        assert payload["total_archived"] == 1

    def test_fetch_by_status_reports_totals(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        _make_status_job(company, office_staff, "One", "approved")
        _make_status_job(company, office_staff, "Two", "approved")

        response = client.get("/api/job/jobs/fetch/approved/")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2
        assert payload["filtered_count"] == 2
        assert {job["name"] for job in payload["jobs"]} == {"One", "Two"}

    def test_fetch_by_column_valid_and_invalid(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        job = _make_status_job(company, office_staff, "Column Job", "in_progress")

        ok = client.get("/api/job/jobs/fetch-by-column/in_progress/")
        assert ok.status_code == 200
        ok_payload = ok.json()
        assert ok_payload["success"] is True
        assert [card["id"] for card in ok_payload["jobs"]] == [str(job.id)]
        assert ok_payload["jobs"][0]["badge_label"] == "In Progress"

        bad = client.get("/api/job/jobs/fetch-by-column/not-a-column/")
        assert bad.status_code == 200  # A no-op result is represented in the payload.
        bad_payload = bad.json()
        assert bad_payload["success"] is False
        assert "Invalid column" in bad_payload["error"]

    def test_status_values(self, client: Client) -> None:
        response = client.get("/api/job/jobs/status-values/")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["statuses"]["in_progress"] == "In Progress"
        assert payload["tooltips"]["in_progress"] == "Status: In Progress"

    def test_advanced_search_endpoint_filters_by_name(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        target = make_job(company, office_staff, name="Handrail polish")
        make_job(company, office_staff, name="Ladder weld")

        response = client.get("/api/job/jobs/advanced-search/", {"name": "handrail"})

        assert response.status_code == 200
        payload = response.json()
        assert [job["id"] for job in payload["jobs"]] == [str(target.id)]
        assert payload["total"] == 1


class TestMutations:
    def test_update_status(self, client: Client, company: Company, office_staff: Staff) -> None:
        job = _make_status_job(company, office_staff, "Mover", "draft")

        response = client.post(
            f"/api/job/jobs/{job.id}/update-status/",
            {"status": "approved"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Job status updated successfully"
        job.refresh_from_db()
        assert job.status == "approved"

    def test_update_status_unknown_job_is_404(self, client: Client) -> None:
        response = client.post(
            f"/api/job/jobs/{uuid4()}/update-status/",
            {"status": "approved"},
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_reorder_requires_anchor_placement_pairing(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        anchor = _make_status_job(company, office_staff, "Anchor", "in_progress")
        mover = _make_status_job(company, office_staff, "Mover", "in_progress")

        missing_placement = client.post(
            f"/api/job/jobs/{mover.id}/reorder/",
            {"anchor_job_id": str(anchor.id)},
            content_type="application/json",
        )
        assert missing_placement.status_code == 400

        ok = client.post(
            f"/api/job/jobs/{mover.id}/reorder/",
            {"anchor_job_id": str(anchor.id), "placement": "below"},
            content_type="application/json",
        )
        assert ok.status_code == 200
        assert ok.json()["message"] == "Job reordered successfully"

    def test_assignment_create_and_destroy(
        self, client: Client, company: Company, office_staff: Staff, workshop_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="Assignment Job")

        created = client.post(
            f"/api/job/job/{job.id}/assignment",
            {"staff_id": str(workshop_staff.id)},
            content_type="application/json",
        )
        assert created.status_code == 200
        assert created.json()["success"] is True
        assert list(job.people.all()) == [workshop_staff]

        removed = client.delete(f"/api/job/job/{job.id}/assignment/{workshop_staff.id}")
        assert removed.status_code == 200
        assert removed.json()["success"] is True
        assert list(job.people.all()) == []

    def test_assignment_unknown_staff_is_400(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="Assignment Errors")

        response = client.post(
            f"/api/job/job/{job.id}/assignment",
            {"staff_id": str(uuid4())},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["error"] == "Staff member not found"


class TestKanbanChanges:
    """Incremental board freshness and version semantics."""

    def test_returns_only_the_changed_card_when_membership_is_unchanged(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        first = _make_status_job(company, office_staff, "First job", "in_progress")
        _make_status_job(company, office_staff, "Second job", "in_progress")
        version = _current_kanban_version()

        first.name = "Renamed first job"
        first.save(staff=office_staff, update_fields=["name"])

        response = client.get("/api/job/jobs/kanban-changes/", {"after": version})

        assert response.status_code == 200
        payload = response.json()
        assert payload["full_refresh_required"] is False
        assert [job["id"] for job in payload["jobs"]] == [str(first.id)]
        assert payload["jobs"][0]["name"] == "Renamed first job"
        assert payload["removed_job_ids"] == []

    def test_reports_a_card_removed_when_it_moves_to_hidden_status(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        first = _make_status_job(company, office_staff, "First job", "in_progress")
        version = _current_kanban_version()

        first.status = "special"
        first.save(staff=office_staff, update_fields=["status"])

        payload = client.get("/api/job/jobs/kanban-changes/", {"after": version}).json()

        assert payload["full_refresh_required"] is False
        assert payload["jobs"] == []
        assert payload["removed_job_ids"] == [str(first.id)]

    def test_returns_a_card_when_it_moves_to_the_archived_column(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        first = _make_status_job(company, office_staff, "First job", "in_progress")
        version = _current_kanban_version()

        first.status = "archived"
        first.save(staff=office_staff, update_fields=["status"])

        payload = client.get("/api/job/jobs/kanban-changes/", {"after": version}).json()

        assert payload["full_refresh_required"] is False
        assert [job["id"] for job in payload["jobs"]] == [str(first.id)]
        assert payload["removed_job_ids"] == []

    def test_requires_full_refresh_when_job_count_changes(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        _make_status_job(company, office_staff, "First job", "in_progress")
        version = _current_kanban_version()

        _make_status_job(company, office_staff, "Newly created job", "in_progress")

        payload = client.get("/api/job/jobs/kanban-changes/", {"after": version}).json()

        assert payload["full_refresh_required"] is True
        assert payload["jobs"] == []
        assert payload["removed_job_ids"] == []

    def test_requires_full_refresh_for_count_neutral_delete_and_create(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        first = _make_status_job(company, office_staff, "First job", "in_progress")
        _make_status_job(company, office_staff, "Second job", "in_progress")
        version = _current_kanban_version()

        first.delete()
        replacement = _make_status_job(company, office_staff, "Replacement", "in_progress")

        payload = client.get("/api/job/jobs/kanban-changes/", {"after": version}).json()

        assert Job.objects.count() == 2
        assert payload["full_refresh_required"] is True
        assert Job.objects.filter(pk=replacement.pk).exists()

    def test_rejects_missing_or_malformed_version(self, client: Client) -> None:
        before = AppError.objects.count()

        missing = client.get("/api/job/jobs/kanban-changes/")
        malformed = client.get("/api/job/jobs/kanban-changes/", {"after": "not-a-version"})

        assert missing.status_code == 400
        assert malformed.status_code == 400
        # The standard envelope persists every HttpError (ADR 0019), one per request.
        assert AppError.objects.count() == before + 2


class TestOverBudgetOnWire:
    def test_fetch_all_serializes_revenue_fields(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        job = _make_status_job(company, office_staff, "Revenue Job", "in_progress")
        job.latest_quote.summary = {"rev": float(Decimal("150.00"))}
        job.latest_quote.save(update_fields=["summary"])
        job.latest_actual.summary = {"rev": float(Decimal("200.00"))}
        job.latest_actual.save(update_fields=["summary"])

        payload = client.get("/api/job/jobs/fetch-all/").json()

        card = payload["active_jobs"][0]
        assert card["quote_revenue"] == 150.0
        assert card["time_and_materials_revenue"] == 200.0
        assert card["over_budget"] is True
