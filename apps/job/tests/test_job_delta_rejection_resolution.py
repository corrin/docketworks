import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models.job_delta_rejection import JobDeltaRejection


@pytest.fixture
def rejection(db):
    return JobDeltaRejection.objects.create(
        reason="stale_etag",
        envelope={},
    )


@pytest.fixture
def staff(db):
    return Staff.objects.create(
        email="resolver@example.test",
        first_name="Rez",
        last_name="Olver",
        password_needs_reset=False,
    )


def test_resolution_defaults_false(rejection):
    assert rejection.resolved is False
    assert rejection.resolved_by is None
    assert rejection.resolved_timestamp is None


def test_mark_resolved_sets_fields(rejection, staff):
    before = timezone.now()
    rejection.mark_resolved(staff)
    rejection.refresh_from_db()

    assert rejection.resolved is True
    assert rejection.resolved_by_id == staff.id
    assert rejection.resolved_timestamp is not None
    assert rejection.resolved_timestamp >= before


def test_mark_unresolved_clears_fields(rejection, staff):
    rejection.mark_resolved(staff)
    rejection.mark_unresolved(staff)
    rejection.refresh_from_db()

    assert rejection.resolved is False
    assert rejection.resolved_by is None
    assert rejection.resolved_timestamp is None
