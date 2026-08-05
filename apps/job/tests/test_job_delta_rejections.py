"""Delta-rejection grouping and resolution across service and model boundaries."""

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import JobDeltaRejection
from apps.job.services import job_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def rejection() -> JobDeltaRejection:
    return JobDeltaRejection.objects.create(reason="stale_etag", envelope={})


class TestResolutionState:
    def test_resolution_defaults_false(self, rejection: JobDeltaRejection) -> None:
        assert rejection.resolved is False
        assert rejection.resolved_by is None
        assert rejection.resolved_timestamp is None

    def test_mark_resolved_sets_fields(
        self, rejection: JobDeltaRejection, office_staff: Staff
    ) -> None:
        before = timezone.now()
        rejection.mark_resolved(office_staff)
        rejection.refresh_from_db()

        assert rejection.resolved is True
        assert rejection.resolved_by_id == office_staff.id
        assert rejection.resolved_timestamp is not None
        assert rejection.resolved_timestamp >= before

    def test_mark_unresolved_clears_fields(
        self, rejection: JobDeltaRejection, office_staff: Staff
    ) -> None:
        rejection.mark_resolved(office_staff)
        rejection.mark_unresolved(office_staff)
        rejection.refresh_from_db()

        assert rejection.resolved is False
        assert rejection.resolved_by is None
        assert rejection.resolved_timestamp is None


class TestGrouping:
    def test_groups_unresolved_by_reason(self) -> None:
        """Catches triage summaries that stop grouping unresolved rejections by reason."""
        JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
        JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
        JobDeltaRejection.objects.create(reason="conflict", envelope={})

        payload = job_service.list_grouped_job_delta_rejections(limit=50, offset=0)

        reasons = {row["reason"]: row["occurrence_count"] for row in payload["results"]}
        assert reasons == {"stale_etag": 2, "conflict": 1}

    def test_excludes_resolved_by_default(self, office_staff: Staff) -> None:
        """Catches closed rejections leaking back into the default operator view."""
        rej = JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
        rej.mark_resolved(office_staff)
        JobDeltaRejection.objects.create(reason="conflict", envelope={})

        payload = job_service.list_grouped_job_delta_rejections(limit=50, offset=0)
        reasons = [row["reason"] for row in payload["results"]]
        assert reasons == ["conflict"]
        assert all(row["resolved"] is False for row in payload["results"])

    def test_resolved_groups_carry_resolved_true(self, office_staff: Staff) -> None:
        """The frontend reads `resolved` per group to choose Resolve vs Unresolve."""
        rej = JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
        rej.mark_resolved(office_staff)
        JobDeltaRejection.objects.create(reason="conflict", envelope={})

        payload = job_service.list_grouped_job_delta_rejections(limit=50, offset=0, resolved=True)
        reasons = [row["reason"] for row in payload["results"]]
        assert reasons == ["stale_etag"]
        assert all(row["resolved"] is True for row in payload["results"])

    def test_individual_list_filters_by_resolved(self, office_staff: Staff) -> None:
        """The individual admin list honours the resolved filter in both directions;
        None shows everything (parity with the System tab's individual list)."""
        open_rej = JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
        done_rej = JobDeltaRejection.objects.create(reason="conflict", envelope={})
        done_rej.mark_resolved(office_staff)

        all_ids = {str(r.id) for r in job_service.list_job_delta_rejections()["results"]}
        assert all_ids == {str(open_rej.id), str(done_rej.id)}

        unresolved = job_service.list_job_delta_rejections(resolved=False)["results"]
        assert [str(r.id) for r in unresolved] == [str(open_rej.id)]

        resolved = job_service.list_job_delta_rejections(resolved=True)["results"]
        assert [str(r.id) for r in resolved] == [str(done_rej.id)]


class TestGroupResolution:
    def test_mark_group_resolved(self, office_staff: Staff) -> None:
        """Catches bulk resolve only closing one rejection in a reason group."""
        JobDeltaRejection.objects.create(reason="conflict", envelope={})
        JobDeltaRejection.objects.create(reason="conflict", envelope={})

        count = job_service.mark_job_delta_rejection_group_resolved("conflict", office_staff)
        assert count == 2
        assert JobDeltaRejection.objects.filter(resolved=True).count() == 2

    def test_mark_group_unresolved(self, office_staff: Staff) -> None:
        """Catches bulk reopen leaving resolved rows hidden from retry triage."""
        for _ in range(2):
            rej = JobDeltaRejection.objects.create(reason="conflict", envelope={})
            rej.mark_resolved(office_staff)

        count = job_service.mark_job_delta_rejection_group_unresolved("conflict", office_staff)
        assert count == 2
        assert JobDeltaRejection.objects.filter(resolved=False).count() == 2
