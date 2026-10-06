"""Consolidate duplicate delivery-date history without losing its undo envelope.

GPT: The historical backfill emitted a specific event beside the original generic
delta event. Keep the original request identity and values, name it accurately,
and remove only its unambiguous, content-identical backfill counterpart. A nearby
event with different or additional content is not evidence of duplication.
"""

import logging
from datetime import timedelta

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

logger = logging.getLogger(__name__)


def consolidate_delivery_dates(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    events = apps.get_model("job", "JobEvent").objects.using(schema_editor.connection.alias)
    specific_events = events.filter(
        event_type="delivery_date_changed",
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
            or set(specific.delta_before) != {"delivery_date"}
            or set(specific.delta_after) != {"delivery_date"}
            or specific.delta_before == specific.delta_after
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
                delta_meta__fields=["delivery_date"],
                detail=specific.detail,
                timestamp__gte=specific.timestamp - timedelta(seconds=1),
                timestamp__lte=specific.timestamp + timedelta(seconds=1),
            )[:2]
        )
        if len(matches) != 1:
            continue
        original = matches[0]
        counterparts = specific_events.filter(
            job_id=original.job_id,
            staff_id=original.staff_id,
            delta_before=original.delta_before,
            delta_after=original.delta_after,
            detail=original.detail,
            timestamp__gte=original.timestamp - timedelta(seconds=1),
            timestamp__lte=original.timestamp + timedelta(seconds=1),
        )
        if counterparts.count() != 1:
            continue
        events.filter(pk=original.pk).update(event_type="delivery_date_changed")
        events.filter(pk=specific.pk).delete()
        consolidated += 1
    logger.info("Consolidated %d duplicate delivery-date event pairs", consolidated)


class Migration(migrations.Migration):
    dependencies = [("job", "0014_job_created_by_not_null")]

    operations = [
        migrations.RunPython(
            consolidate_delivery_dates,
            # One-way: the duplicate entry is deleted, so there is nothing to
            # put back. Reversing leaves the consolidated history in place.
            reverse_code=migrations.RunPython.noop,
        )
    ]
