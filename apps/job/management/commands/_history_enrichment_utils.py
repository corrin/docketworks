"""Shared utilities for HistoricalJob → JobEvent enrichment scripts.

Underscore prefix prevents Django from treating this as a management command.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from apps.client.models import Client, ClientContact
from apps.job.enums import RDTIType, SpeedQualityTradeoff
from apps.job.models.job import Job

logger = logging.getLogger(__name__)

# ── Field-to-event-type mapping ──────────────────────────────────────
# Duplicated from draft migration 0073 for independence.
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

TRACKED_FIELDS = list(FIELD_EVENT_TYPE.keys())

# ── Field display labels ─────────────────────────────────────────────

FIELD_LABELS = {
    "status": "Status",
    "name": "Job name",
    "client_id": "Client",
    "contact_id": "Primary contact",
    "order_number": "Order number",
    "description": "Job description",
    "notes": "Internal notes",
    "delivery_date": "Delivery date",
    "quote_acceptance_date": "Quote acceptance date",
    "pricing_methodology": "Pricing methodology",
    "speed_quality_tradeoff": "Speed/quality tradeoff",
    "charge_out_rate": "Charge out rate",
    "price_cap": "Price cap",
    "priority": "Job priority",
    "paid": "Paid",
    "collected": "Collected",
    "complex_job": "Complex job",
    "rdti_type": "RDTI classification",
    "fully_invoiced": "Fully invoiced",
    "rejected_flag": "Rejected",
}


# ── Choice lookups ───────────────────────────────────────────────────

STATUS_DISPLAY = dict(Job.JOB_STATUS_CHOICES)
PRICING_DISPLAY = dict(Job.PRICING_METHODOLOGY_CHOICES)
SPEED_QUALITY_DISPLAY = dict(SpeedQualityTradeoff.choices)
RDTI_DISPLAY = dict(RDTIType.choices)


# ── FK name caches ───────────────────────────────────────────────────

_client_names: dict | None = None
_contact_names: dict | None = None


def get_client_names() -> dict:
    """Lazy-loaded {id: name} dict for all clients."""
    global _client_names
    if _client_names is None:
        _client_names = dict(Client.objects.values_list("id", "name"))
    return _client_names


def get_contact_names() -> dict:
    """Lazy-loaded {id: name} dict for all contacts."""
    global _contact_names
    if _contact_names is None:
        _contact_names = dict(ClientContact.objects.values_list("id", "name"))
    return _contact_names


# ── Value conversion ─────────────────────────────────────────────────


def safe_value(value):
    """Convert a field value to JSON-safe form."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "hex"):
        return str(value)
    return value


def display_value(field_name: str, raw_value) -> str:
    """Convert a raw field value to its human-readable display string.

    Mirrors the logic in Job._FIELD_HANDLERS for each field type.
    """
    if field_name == "status":
        return str(STATUS_DISPLAY.get(raw_value, raw_value))
    if field_name == "pricing_methodology":
        return str(PRICING_DISPLAY.get(raw_value, raw_value))
    if field_name == "speed_quality_tradeoff":
        return str(SPEED_QUALITY_DISPLAY.get(raw_value, raw_value))
    if field_name == "rdti_type":
        return str(RDTI_DISPLAY.get(raw_value, raw_value or "None"))
    if field_name == "client_id":
        if not raw_value:
            return "Shop Job"
        names = get_client_names()
        return names.get(raw_value, f"Unknown Client (id={raw_value})")
    if field_name == "contact_id":
        if not raw_value:
            return "None"
        names = get_contact_names()
        return names.get(raw_value, f"Unknown Contact (id={raw_value})")
    if field_name in ("paid", "collected", "complex_job", "rejected_flag"):
        return "Yes" if raw_value else "No"
    if field_name == "charge_out_rate":
        return f"${raw_value}/hour"
    if field_name == "price_cap":
        return f"${raw_value or 'None'}"
    if field_name in ("delivery_date", "quote_acceptance_date"):
        if raw_value is None:
            return "None"
        if hasattr(raw_value, "strftime"):
            return raw_value.strftime("%Y-%m-%d")
        return str(raw_value)
    # Text fields and anything else: raw string
    return str(raw_value) if raw_value is not None else "None"


# ── History walking ──────────────────────────────────────────────────


def walk_history_pairs(job_id, HistoricalJob):
    """Generator yielding (prev_record, current_record, changed_fields) tuples.

    changed_fields is a dict of {field_name: (old_value, new_value)} for fields
    that actually changed between the two records.
    """
    records = list(HistoricalJob.objects.filter(id=job_id).order_by("history_date"))
    if len(records) < 2:
        return

    prev = records[0]
    for rec in records[1:]:
        changed = {}
        for field in TRACKED_FIELDS:
            old_val = getattr(prev, field, None)
            new_val = getattr(rec, field, None)
            if old_val != new_val:
                changed[field] = (old_val, new_val)
        if changed:
            yield prev, rec, changed
        prev = rec


def get_first_history_record(job_id, HistoricalJob):
    """Return the first HistoricalJob record for a job (creation record)."""
    return HistoricalJob.objects.filter(id=job_id).order_by("history_date").first()


# ── Event matching ───────────────────────────────────────────────────


def find_matching_event(job_id, event_type, timestamp, window_seconds, JobEvent):
    """Find a JobEvent matching the given criteria within a time window.

    Returns the matching event or None.
    """
    window = timedelta(seconds=window_seconds)
    return JobEvent.objects.filter(
        job_id=job_id,
        event_type=event_type,
        timestamp__gte=timestamp - window,
        timestamp__lte=timestamp + window,
    ).first()


# ── Detail construction ──────────────────────────────────────────────


def build_detail_entry(field_name: str, old_val, new_val) -> dict:
    """Construct a single changes list entry with display values.

    Returns {"field_name": "Status", "old_value": "In Progress", "new_value": "Completed"}
    """
    label = FIELD_LABELS.get(field_name, field_name.replace("_", " ").title())
    return {
        "field_name": label,
        "old_value": display_value(field_name, old_val),
        "new_value": display_value(field_name, new_val),
    }


def infer_event_type(changed_fields: dict) -> str:
    """Pick the most significant event type from a set of changed fields.

    Mirrors Job._infer_event_type logic.
    changed_fields: {field_name: (old_val, new_val)}
    """
    # Rejected flag + archived status → job_rejected
    if "rejected_flag" in changed_fields and "status" in changed_fields:
        _, new_rejected = changed_fields["rejected_flag"]
        _, new_status = changed_fields["status"]
        if new_rejected and new_status == "archived":
            return "job_rejected"

    # Collect event types per field, applying boolean transition logic
    event_types = []
    for field, (old_val, new_val) in changed_fields.items():
        event_type = FIELD_EVENT_TYPE[field]

        # Boolean transition overrides
        if field == "rejected_flag" and not new_val:
            event_type = "job_updated"
        if field == "paid" and not new_val:
            event_type = "payment_updated"
        if field == "collected" and not new_val:
            event_type = "collection_updated"

        event_types.append(event_type)

    if "status_changed" in event_types:
        return "status_changed"
    if len(event_types) == 1:
        return event_types[0]
    return "job_updated"


def build_candidate_event(job_id, history_record, changed_fields: dict) -> dict:
    """Construct a complete candidate JobEvent dict from a HistoricalJob change.

    changed_fields: {field_name: (old_val, new_val)}
    Returns a dict ready for JobEvent.objects.create() (minus the model class).
    """
    delta_before = {}
    delta_after = {}
    detail_changes = []

    for field, (old_val, new_val) in changed_fields.items():
        delta_before[field] = safe_value(old_val)
        delta_after[field] = safe_value(new_val)
        detail_changes.append(build_detail_entry(field, old_val, new_val))

    event_type = infer_event_type(changed_fields)

    return {
        "job_id": job_id,
        "event_type": event_type,
        "timestamp": history_record.history_date,
        "staff_id": history_record.history_user_id,
        "delta_before": delta_before,
        "delta_after": delta_after,
        "detail": {"changes": detail_changes},
        "description": "",
        "schema_version": 0,
    }
