"""Backfill JobEvent structured deltas from HistoricalJob.

Reads HistoricalJob records to reconstruct field changes and creates
structured JobEvent records with delta_before/delta_after JSON fields.
This enables historical state reconstruction from JobEvent alone,
allowing HistoricalJob to be dropped.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import migrations

logger = logging.getLogger(__name__)

# Field-to-event-type mapping, matching _create_change_events in Job model.
# Only fields present in HistoricalJob and tracked by _create_change_events.
FIELD_EVENT_TYPE = {
    "status": "status_changed",
    "name": "job_updated",
    "client_id": "client_changed",
    "contact_id": "contact_changed",
    "order_number": "job_updated",
    "description": "job_updated",
    "notes": "notes_updated",
    "delivery_date": "delivery_date_changed",
    "quote_acceptance_date": "quote_accepted",
    "pricing_methodology": "pricing_changed",
    "speed_quality_tradeoff": "job_updated",
    "charge_out_rate": "pricing_changed",
    "price_cap": "pricing_changed",
    "priority": "priority_changed",
    "paid": "payment_received",
    "collected": "job_collected",
    "complex_job": "job_updated",
    "rdti_type": "job_updated",
    "fully_invoiced": "job_updated",
    "rejected_flag": "job_rejected",
}

# Fields to track — all fields in FIELD_EVENT_TYPE
TRACKED_FIELDS = list(FIELD_EVENT_TYPE.keys())


def _safe_value(value):
    """Convert a field value to JSON-safe form."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "hex"):
        # UUID
        return str(value)
    return value


def backfill_events_from_history(apps, schema_editor):
    """Create structured JobEvents from HistoricalJob field changes."""
    HistoricalJob = apps.get_model("job", "HistoricalJob")
    JobEvent = apps.get_model("job", "JobEvent")
    Job = apps.get_model("job", "Job")

    job_ids = list(
        HistoricalJob.objects.order_by().values_list("id", flat=True).distinct()
    )
    logger.info("Backfilling events for %d jobs from HistoricalJob", len(job_ids))

    created_count = 0
    updated_count = 0

    for job_id in job_ids:
        if not Job.objects.filter(id=job_id).exists():
            continue

        # Get all history records for this job, oldest first
        history_records = list(
            HistoricalJob.objects.filter(id=job_id).order_by("history_date")
        )

        if not history_records:
            continue

        first = history_records[0]

        # Ensure job_created event has structured delta
        existing_created = JobEvent.objects.filter(
            job_id=job_id,
            event_type="job_created",
        ).first()

        initial_delta = {"status": first.status}
        if existing_created:
            if not existing_created.delta_after:
                existing_created.delta_after = initial_delta
                existing_created.save(update_fields=["delta_after"])
                updated_count += 1
        else:
            JobEvent.objects.create(
                job_id=job_id,
                event_type="job_created",
                description="Job created (backfilled from history)",
                timestamp=first.history_date,
                delta_after=initial_delta,
            )
            created_count += 1

        # Walk consecutive records, detect all field changes
        prev = first
        for rec in history_records[1:]:
            for field in TRACKED_FIELDS:
                old_val = getattr(prev, field)
                new_val = getattr(rec, field)

                if old_val == new_val:
                    continue

                event_type = FIELD_EVENT_TYPE[field]
                safe_old = _safe_value(old_val)
                safe_new = _safe_value(new_val)

                # For boolean "on" transitions that have dedicated event types,
                # only create the event on the transition that matches.
                # e.g. rejected_flag: only create job_rejected when False->True
                if field == "rejected_flag" and not new_val:
                    event_type = "job_updated"
                if field == "paid" and not new_val:
                    event_type = "payment_updated"
                if field == "collected" and not new_val:
                    event_type = "collection_updated"

                # Try to find an existing event near this timestamp with this type
                window = timedelta(seconds=1)
                existing = JobEvent.objects.filter(
                    job_id=job_id,
                    event_type=event_type,
                    timestamp__gte=rec.history_date - window,
                    timestamp__lte=rec.history_date + window,
                ).first()

                if existing:
                    # Merge field into existing deltas
                    before = existing.delta_before or {}
                    after = existing.delta_after or {}
                    before[field] = safe_old
                    after[field] = safe_new
                    existing.delta_before = before
                    existing.delta_after = after
                    existing.save(update_fields=["delta_before", "delta_after"])
                    updated_count += 1
                else:
                    JobEvent.objects.create(
                        job_id=job_id,
                        event_type=event_type,
                        description=f"{field} changed (backfilled from history)",
                        timestamp=rec.history_date,
                        delta_before={field: safe_old},
                        delta_after={field: safe_new},
                    )
                    created_count += 1

            prev = rec

    logger.info(
        "Backfill complete: %d events created, %d events updated with deltas",
        created_count,
        updated_count,
    )


class Migration(migrations.Migration):

    dependencies = [
        (
            "job",
            "0072_rename_job_quote_c_job_id_24cfd1_idx_job_jobquot_job_id_c83a63_idx_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_events_from_history,
            migrations.RunPython.noop,
        ),
    ]
