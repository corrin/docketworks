"""Notes history retains complete rich text and a single usable undo identity."""

from collections.abc import Callable
from datetime import timedelta
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

OLD_NOTES = "<p><strong>Full original notes — café</strong></p>" + "<p>Keep this line.</p>" * 12
NEW_NOTES = "<p><em>Updated notes, including commas, quotes and → arrows.</em></p>"


@pytest.fixture
def consolidate() -> Callable[[], None]:
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[("job", "0016_consolidate_notes_events")]
    state = loader.project_state([("job", "0015_consolidate_delivery_date_events")])
    operation = next(op for op in migration.operations if isinstance(op, migrations.RunPython))

    def run() -> None:
        with connection.schema_editor() as editor:
            operation.code(state.apps, editor)

    return run


def _pair(
    job: Job, staff: Staff, before: str | None, after: str | None, null_label: str = ""
) -> tuple[JobEvent, JobEvent]:
    specific = JobEvent.objects.create(
        job=job,
        staff=staff,
        event_type="notes_updated",
        delta_before={"notes": before},
        delta_after={"notes": after},
        detail={
            "changes": [
                {
                    "field_name": "Internal notes",
                    "old_value": str(before)[:50] + "...",
                    "new_value": "",
                }
            ]
        },
    )
    original = JobEvent.objects.create(
        job=job,
        staff=staff,
        event_type="job_updated",
        schema_version=1,
        change_id=uuid4(),
        delta_before={"notes": before},
        delta_after={"notes": after},
        delta_meta={"fields": ["notes"], "actor_id": str(staff.id)},
        delta_checksum=compute_job_delta_checksum(job.id, {"notes": before}, ["notes"]),
        detail={
            "changes": [
                {
                    "field_name": "Internal notes",
                    "old_value": before if before is not None else null_label,
                    "new_value": after if after is not None else null_label,
                }
            ]
        },
    )
    JobEvent.objects.filter(pk=original.pk).update(
        timestamp=specific.timestamp + timedelta(milliseconds=4)
    )
    return specific, original


@pytest.mark.parametrize(
    "transition",
    [
        (None, NEW_NOTES, "None"),
        (None, NEW_NOTES, ""),
        (OLD_NOTES, NEW_NOTES, ""),
        (OLD_NOTES, None, ""),
    ],
)
def test_complete_notes_and_undo_survive_the_lossy_duplicate(
    job: Job,
    office_staff: Staff,
    consolidate: Callable[[], None],
    transition: tuple[str | None, str | None, str],
) -> None:
    before, after, null_label = transition
    job.notes = after
    job.save(staff=office_staff)
    JobEvent.objects.filter(job=job).update(timestamp=timezone.now() - timedelta(days=1))
    baseline = set(JobEvent.objects.filter(job=job).values_list("pk", flat=True))
    specific, original = _pair(job, office_staff, before, after, null_label)
    original_row = JobEvent.objects.values().get(pk=original.pk)

    consolidate()
    consolidate()

    events = JobEvent.objects.filter(job=job).exclude(pk__in=baseline)
    assert events.count() == 1
    assert not JobEvent.objects.filter(pk=specific.pk).exists()
    assert events.values().get() == {**original_row, "event_type": "notes_updated"}
    original.refresh_from_db()
    assert job_service._undo_info(original)[0]
    assert original.change_id is not None
    job_service.undo_job_change(
        job.id,
        original.change_id,
        office_staff,
        generate_updated_at_etag("job", job.id, job.updated_at),
    )
    job.refresh_from_db()
    assert job.notes == before
    assert events.count() == 2
    reversal = events.exclude(pk=original.pk).get()
    assert reversal.event_type == "notes_updated"
    assert reversal.delta_after == {"notes": before}
    assert reversal.delta_meta is not None
    assert reversal.delta_meta["undo_of_change_id"] == str(original.change_id)


@pytest.mark.parametrize(
    "case",
    [
        "same_preview_different_html",
        "additional_field",
        "missing_delta",
        "truncated_original",
        "additional_detail",
        "other_staff",
        "outside_window",
        "competing_specific",
        "competing_original",
    ],
)
def test_uncertain_notes_pairs_are_unchanged(
    job: Job,
    office_staff: Staff,
    workshop_staff: Staff,
    consolidate: Callable[[], None],
    case: str,
) -> None:
    specific, original = _pair(job, office_staff, OLD_NOTES, NEW_NOTES)
    if case == "same_preview_different_html":
        original.delta_after = {"notes": NEW_NOTES + "<p>Another change</p>"}
    elif case == "additional_field":
        original.delta_before = {"notes": OLD_NOTES, "order_number": None}
        original.delta_after = {"notes": NEW_NOTES, "order_number": "PO-2"}
        original.delta_meta = {"fields": ["notes", "order_number"]}
    elif case == "missing_delta":
        original.delta_before = None
    elif case == "truncated_original":
        original.detail = specific.detail
    elif case == "additional_detail":
        specific.detail = {**specific.detail, "note_text": "Separate information"}
        specific.save()
    elif case == "other_staff":
        original.staff = workshop_staff
    elif case == "outside_window":
        original.timestamp = specific.timestamp + timedelta(seconds=2)
    else:
        competing = JobEvent.objects.get(
            pk=specific.pk if case == "competing_specific" else original.pk
        )
        competing.pk = uuid4()
        if case == "competing_original":
            competing.change_id = uuid4()
        competing.save(force_insert=True)
        JobEvent.objects.filter(pk=competing.pk).update(timestamp=specific.timestamp)
    original.save()
    rows = list(JobEvent.objects.filter(job=job).order_by("pk").values())

    consolidate()

    assert list(JobEvent.objects.filter(job=job).order_by("pk").values()) == rows


def test_successive_notes_edits_remain_separate_and_stale_undo_is_refused(
    job: Job,
    office_staff: Staff,
    consolidate: Callable[[], None],
) -> None:
    job.notes = NEW_NOTES
    job.save(staff=office_staff)
    JobEvent.objects.filter(job=job).update(timestamp=timezone.now() - timedelta(days=1))
    baseline = set(JobEvent.objects.filter(job=job).values_list("pk", flat=True))
    _, first = _pair(job, office_staff, None, OLD_NOTES)
    _, second = _pair(job, office_staff, OLD_NOTES, NEW_NOTES)

    consolidate()

    events = JobEvent.objects.filter(job=job).exclude(pk__in=baseline)
    assert set(events.values_list("pk", flat=True)) == {first.pk, second.pk}
    assert first.change_id is not None
    with pytest.raises(PreconditionFailedError):
        job_service.undo_job_change(
            job.id,
            first.change_id,
            office_staff,
            generate_updated_at_etag("job", job.id, job.updated_at),
        )
    job.refresh_from_db()
    assert job.notes == NEW_NOTES
    assert events.count() == 2
