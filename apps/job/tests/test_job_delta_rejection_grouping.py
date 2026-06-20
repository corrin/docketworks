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
    """Catches triage summaries that stop grouping unresolved rejections by reason."""
    JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    JobDeltaRejection.objects.create(reason="conflict", envelope={})

    payload = JobRestService.list_grouped_job_delta_rejections(limit=50, offset=0)

    reasons = {row["reason"]: row["occurrence_count"] for row in payload["results"]}
    assert reasons == {"stale_etag": 2, "conflict": 1}


def test_excludes_resolved_by_default(db, staff):
    """Catches closed rejections leaking back into the default operator view."""
    rej = JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    rej.mark_resolved(staff)
    JobDeltaRejection.objects.create(reason="conflict", envelope={})

    payload = JobRestService.list_grouped_job_delta_rejections(limit=50, offset=0)
    reasons = [row["reason"] for row in payload["results"]]
    assert reasons == ["conflict"]
    assert all(row["resolved"] is False for row in payload["results"])


def test_resolved_groups_carry_resolved_true(db: None, staff: Staff) -> None:
    """The frontend reads `resolved` per group to choose Resolve vs Unresolve."""
    rej = JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    rej.mark_resolved(staff)
    JobDeltaRejection.objects.create(reason="conflict", envelope={})

    payload = JobRestService.list_grouped_job_delta_rejections(
        limit=50, offset=0, resolved=True
    )
    reasons = [row["reason"] for row in payload["results"]]
    assert reasons == ["stale_etag"]
    assert all(row["resolved"] is True for row in payload["results"])


def test_individual_list_filters_by_resolved(db: None, staff: Staff) -> None:
    """The individual admin list honours the resolved filter in both directions;
    None shows everything (parity with the System tab's individual list)."""
    open_rej = JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    done_rej = JobDeltaRejection.objects.create(reason="conflict", envelope={})
    done_rej.mark_resolved(staff)

    all_ids = {str(r.id) for r in JobRestService.list_job_delta_rejections()["results"]}
    assert all_ids == {str(open_rej.id), str(done_rej.id)}

    unresolved = JobRestService.list_job_delta_rejections(resolved=False)["results"]
    assert [str(r.id) for r in unresolved] == [str(open_rej.id)]

    resolved = JobRestService.list_job_delta_rejections(resolved=True)["results"]
    assert [str(r.id) for r in resolved] == [str(done_rej.id)]


def test_mark_group_resolved(db, staff):
    """Catches bulk resolve only closing one rejection in a reason group."""
    JobDeltaRejection.objects.create(reason="conflict", envelope={})
    JobDeltaRejection.objects.create(reason="conflict", envelope={})

    count = JobRestService.mark_job_delta_rejection_group_resolved("conflict", staff)
    assert count == 2
    assert JobDeltaRejection.objects.filter(resolved=True).count() == 2


def test_mark_group_unresolved(db, staff):
    """Catches bulk reopen leaving resolved rows hidden from retry triage."""
    for _ in range(2):
        rej = JobDeltaRejection.objects.create(reason="conflict", envelope={})
        rej.mark_resolved(staff)

    count = JobRestService.mark_job_delta_rejection_group_unresolved("conflict", staff)
    assert count == 2
    assert JobDeltaRejection.objects.filter(resolved=False).count() == 2
