"""Undo of a job event written before its fields were trimmed reverses what changed."""

from collections.abc import Callable
from uuid import uuid4

import pytest
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader

from apps.accounts.models import Staff
from apps.core.etag import generate_updated_at_etag
from apps.job.models import Job, JobEvent
from apps.job.services import job_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def trim() -> Callable[[], None]:
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[("job", "0019_trim_undo_fields")]
    state = loader.project_state([("job", "0018_job_status_valid")])
    operation = next(op for op in migration.operations if isinstance(op, migrations.RunPython))

    def run() -> None:
        with connection.schema_editor() as editor:
            operation.code(state.apps, editor)

    return run


def test_an_old_event_naming_an_unchanged_field_can_be_undone(
    trim: Callable[[], None], job: Job, office_staff: Staff
) -> None:
    """Guards 0019_trim_undo_fields: job_status maps to status, unchanged names go."""
    change_id = uuid4()
    original = job.description
    job.description = "Edited"
    job.save(
        staff=office_staff,
        update_fields=["description"],
        schema_version=1,
        change_id=change_id,
        delta_meta={"fields": ["description"]},
    )
    event = JobEvent.objects.get(change_id=change_id)
    # As written before the trim: every field the delta carried.
    event.delta_meta = {"fields": ["description", "notes", "job_status"]}
    event.save(update_fields=["delta_meta"])

    trim()

    event.refresh_from_db()
    assert event.delta_meta["fields"] == ["description"]
    job.refresh_from_db()
    etag = generate_updated_at_etag("job", job.id, job.updated_at)
    assert (
        job_service.undo_job_change(job.id, change_id, office_staff, etag).description == original
    )
