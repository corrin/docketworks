"""Keep one complete, undoable entry for each proven duplicate notes edit.

GPT: The old specific entry carries a truncated, sometimes incorrectly parsed
preview. Its raw deltas still match the original request exactly. Keep that
request's full HTML, display detail and undo identity; never reconstruct notes
from the preview or equate two edits just because their previews look alike.
"""

import logging
from datetime import timedelta

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

logger = logging.getLogger(__name__)


def _notes_only_detail(detail: object) -> bool:
    if not isinstance(detail, dict) or set(detail) != {"changes"}:
        return False
    changes = detail["changes"]
    if not isinstance(changes, list) or len(changes) != 1:
        return False
    change = changes[0]
    return (
        isinstance(change, dict)
        and set(change) == {"field_name", "old_value", "new_value"}
        and change["field_name"] == "Internal notes"
        and isinstance(change["old_value"], str)
        and isinstance(change["new_value"], str)
    )


def consolidate_notes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    events = apps.get_model("job", "JobEvent").objects.using(schema_editor.connection.alias)
    specific_events = events.filter(
        event_type="notes_updated",
        schema_version=0,
        change_id__isnull=True,
        staff_id__isnull=False,
        delta_meta__isnull=True,
        delta_checksum__isnull=True,
        dedup_hash__isnull=True,
    )
    consolidated = 0
    for specific in specific_events.order_by("timestamp", "pk").iterator():
        if (
            not isinstance(specific.delta_before, dict)
            or not isinstance(specific.delta_after, dict)
            or set(specific.delta_before) != {"notes"}
            or set(specific.delta_after) != {"notes"}
            or specific.delta_before == specific.delta_after
            or not _notes_only_detail(specific.detail)
        ):
            continue
        before, after = specific.delta_before["notes"], specific.delta_after["notes"]
        if not (before is None or isinstance(before, str)) or not (
            after is None or isinstance(after, str)
        ):
            continue
        matches = list(
            events.filter(
                job_id=specific.job_id,
                staff_id=specific.staff_id,
                event_type="job_updated",
                schema_version=1,
                change_id__isnull=False,
                delta_before=specific.delta_before,
                delta_after=specific.delta_after,
                delta_meta__fields=["notes"],
                timestamp__gte=specific.timestamp - timedelta(seconds=1),
                timestamp__lte=specific.timestamp + timedelta(seconds=1),
            )[:2]
        )
        if len(matches) != 1:
            continue
        original = matches[0]
        if not _notes_only_detail(original.detail):
            continue
        change = original.detail["changes"][0]
        if change["old_value"] not in (("", "None") if before is None else (before,)) or change[
            "new_value"
        ] not in (("", "None") if after is None else (after,)):
            continue
        counterparts = specific_events.filter(
            job_id=original.job_id,
            staff_id=original.staff_id,
            delta_before=original.delta_before,
            delta_after=original.delta_after,
            timestamp__gte=original.timestamp - timedelta(seconds=1),
            timestamp__lte=original.timestamp + timedelta(seconds=1),
        )
        if counterparts.count() != 1:
            continue
        events.filter(pk=original.pk).update(event_type="notes_updated")
        events.filter(pk=specific.pk).delete()
        consolidated += 1
    logger.info("Consolidated %d duplicate notes event pairs", consolidated)


class Migration(migrations.Migration):
    dependencies = [("job", "0015_consolidate_delivery_date_events")]

    operations = [
        migrations.RunPython(
            consolidate_notes,
            # One-way: the duplicate entry is deleted, so there is nothing to
            # put back. Reversing leaves the consolidated history in place.
            reverse_code=migrations.RunPython.noop,
        )
    ]
