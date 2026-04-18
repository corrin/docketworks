import pytest

from apps.accounts.models import Staff
from apps.job.models.job_delta_rejection import JobDeltaRejection
from apps.job.services.job_rest_service import JobRestService


@pytest.fixture
def staff(db):
    return Staff.objects.create(
        email="grouper@example.test",
        first_name="G",
        last_name="R",
        password_needs_reset=False,
    )


def test_groups_unresolved_by_reason(db):
    JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    JobDeltaRejection.objects.create(reason="conflict", envelope={})

    payload = JobRestService.list_grouped_job_delta_rejections(limit=50, offset=0)

    reasons = {row["reason"]: row["occurrence_count"] for row in payload["results"]}
    assert reasons == {"stale_etag": 2, "conflict": 1}


def test_excludes_resolved_by_default(db, staff):
    rej = JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    rej.mark_resolved(staff)
    JobDeltaRejection.objects.create(reason="conflict", envelope={})

    payload = JobRestService.list_grouped_job_delta_rejections(limit=50, offset=0)
    reasons = [row["reason"] for row in payload["results"]]
    assert reasons == ["conflict"]


def test_mark_group_resolved(db, staff):
    JobDeltaRejection.objects.create(reason="conflict", envelope={})
    JobDeltaRejection.objects.create(reason="conflict", envelope={})

    count = JobRestService.mark_job_delta_rejection_group_resolved("conflict", staff)
    assert count == 2
    assert JobDeltaRejection.objects.filter(resolved=True).count() == 2


def test_mark_group_unresolved(db, staff):
    for _ in range(2):
        rej = JobDeltaRejection.objects.create(reason="conflict", envelope={})
        rej.mark_resolved(staff)

    count = JobRestService.mark_job_delta_rejection_group_unresolved("conflict", staff)
    assert count == 2
    assert JobDeltaRejection.objects.filter(resolved=False).count() == 2
