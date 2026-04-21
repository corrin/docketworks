"""Backfill JobEvent.detail from existing description, delta_before/after, and delta_meta.

Populates structured detail data so build_description() can generate descriptions
dynamically instead of relying on the stored description column.

Also normalises legacy event_type values:
- status_change → status_changed
- created → job_created
"""

import logging
import re

from django.db import migrations

logger = logging.getLogger(__name__)

# Field label mapping for delta keys → human-readable names
FIELD_LABELS = {
    "status": "Status",
    "job_status": "Status",
    "name": "Job name",
    "description": "Job description",
    "notes": "Internal notes",
    "order_number": "Order number",
    "client_id": "Client",
    "contact_id": "Primary contact",
    "delivery_date": "Delivery date",
    "pricing_methodology": "Pricing methodology",
    "charge_out_rate": "Charge out rate",
    "price_cap": "Price cap",
    "priority": "Job priority",
    "paid": "Paid",
    "collected": "Collected",
    "complex_job": "Complex job",
    "rdti_type": "RDTI classification",
    "rejected_flag": "Rejected",
    "speed_quality_tradeoff": "Speed/quality tradeoff",
    "fully_invoiced": "Fully invoiced",
}


def _make_changes_list(field_name, old_value, new_value):
    return {
        "changes": [
            {
                "field_name": field_name,
                "old_value": str(old_value),
                "new_value": str(new_value),
            }
        ]
    }


def _backfill_status_changed(event):
    """Parse: Status changed from 'X' to 'Y'. Job moved to new workflow stage"""
    m = re.match(r"Status changed from '([^']+)' to '([^']+)'", event.description)
    if m:
        return _make_changes_list("Status", m.group(1), m.group(2))
    # Older unquoted format: "Job status changed from X to Y"
    m = re.match(r"Job status changed from (\S+) to (\S+)", event.description)
    if m:
        return _make_changes_list("Status", m.group(1), m.group(2))
    return None


def _backfill_status_change_legacy(event):
    """Parse old format: Job status changed from X to Y"""
    m = re.match(r"Job status changed from (\S+) to (\S+)", event.description)
    if m:
        return _make_changes_list("Status", m.group(1), m.group(2))
    return None


def _backfill_job_created(event):
    """Parse: New job 'X' created for client Y (Contact: Z). Initial status: A. Pricing methodology: B."""
    m = re.match(
        r"New job '(.+?)' created for client (.+?)(?:\s*\(Contact: (.+?)\))?\.\s*"
        r"Initial status: (.+?)\.\s*Pricing methodology: (.+?)\.",
        event.description,
    )
    if m:
        detail = {
            "job_name": m.group(1),
            "client_name": m.group(2).strip(),
            "initial_status": m.group(4),
            "pricing_methodology": m.group(5),
        }
        if m.group(3):
            detail["contact_name"] = m.group(3)
        return detail
    return None


def _backfill_invoice_created(event):
    """Parse: Invoice INV-XXXXX created in Xero"""
    m = re.match(r"Invoice ([\w-]+) created in Xero", event.description)
    if m:
        return {"xero_invoice_number": m.group(1)}
    return None


def _backfill_delivery_date_changed(event):
    """Parse: Delivery date changed from 'X' to 'Y'"""
    m = re.match(
        r"Delivery date changed from '([^']+)' to '([^']+)'", event.description
    )
    if m:
        return _make_changes_list("Delivery date", m.group(1), m.group(2))
    return None


def _backfill_pricing_changed(event):
    """Parse: Pricing methodology changed from 'X' to 'Y' or Charge out rate / Price cap"""
    m = re.match(
        r"Pricing methodology changed from '([^']+)' to '([^']+)'", event.description
    )
    if m:
        return _make_changes_list("Pricing methodology", m.group(1), m.group(2))
    m = re.match(
        r"Charge out rate changed from \$(.+?)/hour to \$(.+?)/hour", event.description
    )
    if m:
        return _make_changes_list(
            "Charge out rate", f"${m.group(1)}/hour", f"${m.group(2)}/hour"
        )
    m = re.match(r"Price cap changed from \$(.+?) to \$(.+?)$", event.description)
    if m:
        return _make_changes_list("Price cap", f"${m.group(1)}", f"${m.group(2)}")
    return None


def _backfill_contact_changed(event):
    """Parse: Primary contact changed from 'X' to 'Y'"""
    m = re.match(
        r"Primary contact changed from '([^']+)' to '([^']+)'", event.description
    )
    if m:
        return _make_changes_list("Primary contact", m.group(1), m.group(2))
    return None


def _backfill_client_changed(event):
    """Parse: Client changed from 'X' to 'Y'"""
    m = re.match(r"Client changed from '([^']+)' to '([^']+)'", event.description)
    if m:
        return _make_changes_list("Client", m.group(1), m.group(2))
    return None


def _backfill_notes_updated(event):
    """Parse: Internal notes updated/added/removed. Previous content: '...'"""
    m = re.match(
        r"Internal notes updated\. Previous content: '(.*)'",
        event.description,
        re.DOTALL,
    )
    if m:
        return _make_changes_list("Internal notes", m.group(1), "")
    m = re.match(r"Internal notes added: '(.*)'", event.description, re.DOTALL)
    if m:
        return _make_changes_list("Internal notes", "", m.group(1))
    m = re.match(
        r"Internal notes removed\. Previous content: '(.*)'",
        event.description,
        re.DOTALL,
    )
    if m:
        return _make_changes_list("Internal notes", m.group(1), "")
    return None


def _backfill_delivery_docket(event):
    """Copy from delta_meta: filename, file_id"""
    meta = event.delta_meta or {}
    if "filename" in meta:
        detail = {"filename": meta["filename"]}
        if "file_id" in meta:
            detail["file_id"] = meta["file_id"]
        return detail
    return None


def _backfill_jsa_generated(event):
    """Copy from delta_meta + parse title from description"""
    meta = event.delta_meta or {}
    detail = {}
    if "jsa_id" in meta:
        detail["jsa_id"] = meta["jsa_id"]
    if "google_doc_url" in meta:
        detail["google_doc_url"] = meta["google_doc_url"]
    # Parse title: "JSA generated: <title>" or "JSA linked: <title>"
    m = re.match(r"JSA (?:generated|linked): (.+)", event.description)
    if m:
        detail["jsa_title"] = m.group(1)
    if detail:
        return detail
    return None


def _backfill_job_updated_with_deltas(event):
    """Build changes list from delta_before/delta_after."""
    before = event.delta_before or {}
    after = event.delta_after or {}
    changes = []
    for field in before:
        label = FIELD_LABELS.get(field, field.replace("_", " ").title())
        old_val = before.get(field)
        new_val = after.get(field)
        changes.append(
            {
                "field_name": label,
                "old_value": str(old_val) if old_val is not None else "None",
                "new_value": str(new_val) if new_val is not None else "None",
            }
        )
    if changes:
        return {"changes": changes}
    return None


def _backfill_job_updated_no_deltas(event):
    """Parse parseable job_updated descriptions without deltas."""
    d = event.description

    m = re.match(r"Job name changed from '(.+?)' to '(.+?)'", d)
    if m:
        return _make_changes_list("Job name", m.group(1), m.group(2))

    m = re.match(r"Order number changed from '(.+?)' to '(.+?)'", d)
    if m:
        return _make_changes_list("Order number", m.group(1), m.group(2))

    m = re.match(r"Job description updated\. Previous content: '(.*)'", d, re.DOTALL)
    if m:
        return _make_changes_list("Job description", m.group(1), "")

    m = re.match(r"Job description added: '(.*)'", d, re.DOTALL)
    if m:
        return _make_changes_list("Job description", "", m.group(1))

    m = re.match(r"Job description removed\. Previous content: '(.*)'", d, re.DOTALL)
    if m:
        return _make_changes_list("Job description", m.group(1), "")

    m = re.match(r"Speed/quality tradeoff changed from '([^']+)' to '([^']+)'", d)
    if m:
        return _make_changes_list("Speed/quality tradeoff", m.group(1), m.group(2))

    m = re.match(r"RDTI classification changed from '([^']+)' to '([^']+)'", d)
    if m:
        return _make_changes_list("RDTI classification", m.group(1), m.group(2))

    m = re.match(r"Xero pay item changed from '([^']+)' to '([^']+)'", d)
    if m:
        return _make_changes_list("Xero pay item", m.group(1), m.group(2))

    if (
        d
        == "Job marked as COMPLEX JOB. This job requires special attention or has complex requirements"
    ):
        return _make_changes_list("Complex job", "No", "Yes")

    if d == "Job no longer marked as complex job":
        return _make_changes_list("Complex job", "Yes", "No")

    if re.match(r"Job marked as rejected", d):
        return _make_changes_list("Rejected", "No", "Yes")

    # Status without quotes (old format in job_updated)
    m = re.match(r"Status changed from (\S+) to (\S+)", d)
    if m:
        return _make_changes_list("Status", m.group(1), m.group(2))

    return None


def backfill_detail(apps, schema_editor):
    """Populate detail field on all existing JobEvent rows."""
    JobEvent = apps.get_model("job", "JobEvent")

    total = JobEvent.objects.count()
    structured = 0
    legacy = 0
    skipped = 0

    # Process in batches to avoid memory issues
    batch_size = 500
    last_id = None

    while True:
        queryset = JobEvent.objects.filter(detail={}).order_by("id")
        if last_id:
            queryset = queryset.filter(id__gt=last_id)
        batch = list(queryset[:batch_size])
        if not batch:
            break

        to_update = []
        for event in batch:
            last_id = event.id
            detail = None
            new_event_type = None

            if event.event_type == "status_changed":
                detail = _backfill_status_changed(event)

            elif event.event_type == "status_change":
                detail = _backfill_status_change_legacy(event)
                new_event_type = "status_changed"

            elif event.event_type == "job_created":
                detail = _backfill_job_created(event)

            elif event.event_type == "created":
                new_event_type = "job_created"
                # No structured data extractable

            elif event.event_type == "invoice_created":
                detail = _backfill_invoice_created(event)

            elif event.event_type == "manual_note":
                detail = {"note_text": event.description}

            elif event.event_type == "delivery_docket_generated":
                detail = _backfill_delivery_docket(event)

            elif event.event_type == "jsa_generated":
                detail = _backfill_jsa_generated(event)

            elif event.event_type == "delivery_date_changed":
                detail = _backfill_delivery_date_changed(event)

            elif event.event_type == "notes_updated":
                detail = _backfill_notes_updated(event)

            elif event.event_type == "pricing_changed":
                detail = _backfill_pricing_changed(event)

            elif event.event_type == "contact_changed":
                detail = _backfill_contact_changed(event)

            elif event.event_type == "client_changed":
                detail = _backfill_client_changed(event)

            elif event.event_type == "payment_received":
                detail = _make_changes_list("Paid", "No", "Yes")

            elif event.event_type == "payment_updated":
                detail = _make_changes_list("Paid", "Yes", "No")

            elif event.event_type == "job_rejected":
                detail = _make_changes_list("Rejected", "No", "Yes")

            elif event.event_type == "job_updated":
                if event.delta_before:
                    detail = _backfill_job_updated_with_deltas(event)
                else:
                    detail = _backfill_job_updated_no_deltas(event)

            # If the type-specific parser couldn't extract structure, try the
            # raw delta_before/delta_after — events backfilled from
            # HistoricalJob (migration 0075) store the actual change there
            # with only a generic description, so regex-on-description fails
            # but the underlying data is intact.
            if not detail and event.delta_before:
                detail = _backfill_job_updated_with_deltas(event)

            if detail:
                event.detail = detail
                structured += 1
            else:
                event.detail = {"legacy_description": event.description}
                legacy += 1

            if new_event_type:
                event.event_type = new_event_type

            to_update.append(event)

        if to_update:
            JobEvent.objects.bulk_update(
                to_update, ["detail", "event_type"], batch_size=batch_size
            )

    logger.info(
        "Backfill complete: %d total, %d structured, %d legacy_description, %d skipped",
        total,
        structured,
        legacy,
        skipped,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("job", "0076_add_jobevent_detail_field"),
    ]

    operations = [
        migrations.RunPython(
            backfill_detail,
            migrations.RunPython.noop,
        ),
    ]
