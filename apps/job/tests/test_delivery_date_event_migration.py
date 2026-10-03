"""A delivery-date edit has one history entry carrying its original undo identity."""

from collections.abc import Callable
from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.etag import PreconditionFailedError, generate_updated_at_etag
from apps.job.models import Job, JobEvent
from apps.job.services import job_service
from apps.job.services.delta_checksum import compute_job_delta_checksum

pytestmark = pytest.mark.django_db


@pytest.fixture
def consolidate() -> Callable[[], None]:
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[("job", "0015_consolidate_delivery_date_events")]
    state = loader.project_state([("job", "0014_job_created_by_not_null")])
    operation = next(op for op in migration.operations if isinstance(op, migrations.RunPython))

    def run() -> None:
        with connection.schema_editor() as editor:
            operation.code(state.apps, editor)

    return run


def _pair(
    job: Job, staff: Staff, before: str | None, after: str | None
) -> tuple[JobEvent, JobEvent]:
    delta_before = {"delivery_date": before}
    delta_after = {"delivery_date": after}
    detail = {
        "changes": [
            {"field_name": "Delivery date", "old_value": str(before), "new_value": str(after)}
        ]
    }
    specific = JobEvent.objects.create(
        job=job,
        staff=staff,
        event_type="delivery_date_changed",
        delta_before=delta_before,
        delta_after=delta_after,
        detail=detail,
    )
    generic = JobEvent.objects.create(
        job=job,
        staff=staff,
        event_type="job_updated",
        schema_version=1,
        change_id=uuid4(),
        delta_before=delta_before,
        delta_after=delta_after,
        delta_meta={
            "fields": ["delivery_date"],
            "actor_id": str(staff.id),
            "made_at": timezone.now().isoformat(),
            "etag": generate_updated_at_etag("job", job.id, job.updated_at),
        },
        delta_checksum=compute_job_delta_checksum(job.id, delta_before, ["delivery_date"]),
        detail=detail,
    )
    JobEvent.objects.filter(pk=generic.pk).update(
        timestamp=specific.timestamp + timedelta(milliseconds=4)
    )
    return specific, generic


@pytest.mark.parametrize(
    ("before", "after"),
    [(None, "2026-10-03"), ("2026-10-03", "2026-10-04"), ("2026-10-03", None)],
)
def test_consolidated_event_keeps_identity_and_can_undo(
    job: Job,
    office_staff: Staff,
    consolidate: Callable[[], None],
    before: str | None,
    after: str | None,
) -> None:
    job.delivery_date = date.fromisoformat(after) if after is not None else None
    job.save(staff=office_staff)
    JobEvent.objects.filter(job=job).update(timestamp=timezone.now() - timedelta(days=1))
    baseline = set(JobEvent.objects.filter(job=job).values_list("pk", flat=True))
    specific, generic = _pair(job, office_staff, before, after)
    original = JobEvent.objects.values().get(pk=generic.pk)

    consolidate()
    consolidate()

    remaining = JobEvent.objects.filter(job=job).exclude(pk__in=baseline)
    assert remaining.count() == 1
    assert not JobEvent.objects.filter(pk=specific.pk).exists()
    assert remaining.values().get() == {**original, "event_type": "delivery_date_changed"}
    generic.refresh_from_db()
    assert job_service._undo_info(generic)[0] is True
    assert generic.change_id is not None
    job_service.undo_job_change(
        job.id,
        generic.change_id,
        office_staff,
        generate_updated_at_etag("job", job.id, job.updated_at),
    )

    job.refresh_from_db()
    assert job.delivery_date == (date.fromisoformat(before) if before is not None else None)
    assert remaining.count() == 2
    reversal = remaining.exclude(pk=generic.pk).get()
    assert reversal.event_type == "delivery_date_changed"
    assert reversal.delta_before == {"delivery_date": after}
    assert reversal.delta_after == {"delivery_date": before}
    assert reversal.delta_meta is not None
    assert reversal.delta_meta["undo_of_change_id"] == str(generic.change_id)


@pytest.mark.parametrize(
    "case",
    [
        "other_field",
        "other_value",
        "missing_before",
        "other_staff",
        "outside_window",
        "ambiguous_specific",
        "ambiguous_generic",
    ],
)
def test_does_not_merge_unproven_pairs(
    job: Job,
    office_staff: Staff,
    workshop_staff: Staff,
    consolidate: Callable[[], None],
    case: str,
) -> None:
    specific, generic = _pair(job, office_staff, None, "2026-10-03")
    if case == "other_field":
        generic.delta_before = {"delivery_date": None, "order_number": None}
        generic.delta_after = {"delivery_date": "2026-10-03", "order_number": "PO-123"}
        generic.delta_meta = {"fields": ["delivery_date", "order_number"]}
    elif case == "other_value":
        generic.delta_after = {"delivery_date": "2026-10-04"}
    elif case == "missing_before":
        generic.delta_before = None
    elif case == "other_staff":
        generic.staff = workshop_staff
    elif case == "outside_window":
        generic.timestamp = specific.timestamp + timedelta(seconds=2)
    else:
        duplicate = JobEvent.objects.get(
            pk=specific.pk if case == "ambiguous_specific" else generic.pk
        )
        duplicate.pk = uuid4()
        if case == "ambiguous_generic":
            duplicate.change_id = uuid4()
        duplicate.save(force_insert=True)
    generic.save()
    before_rows = list(JobEvent.objects.filter(job=job).order_by("pk").values())

    consolidate()

    assert list(JobEvent.objects.filter(job=job).order_by("pk").values()) == before_rows


def test_successive_date_changes_survive_and_old_undo_cannot_overwrite_them(
    job: Job, office_staff: Staff, consolidate: Callable[[], None]
) -> None:
    job.delivery_date = date(2026, 10, 4)
    job.save(staff=office_staff)
    JobEvent.objects.filter(job=job).update(timestamp=timezone.now() - timedelta(days=1))
    baseline = set(JobEvent.objects.filter(job=job).values_list("pk", flat=True))
    _, first = _pair(job, office_staff, None, "2026-10-03")
    _, second = _pair(job, office_staff, "2026-10-03", "2026-10-04")

    consolidate()

    events = JobEvent.objects.filter(job=job).exclude(pk__in=baseline)
    assert set(events.values_list("pk", flat=True)) == {first.pk, second.pk}
    assert set(events.values_list("event_type", flat=True)) == {"delivery_date_changed"}
    assert first.change_id is not None
    with pytest.raises(PreconditionFailedError):
        job_service.undo_job_change(
            job.id,
            first.change_id,
            office_staff,
            generate_updated_at_etag("job", job.id, job.updated_at),
        )
    job.refresh_from_db()
    assert job.delivery_date == date(2026, 10, 4)
    assert events.count() == 2
