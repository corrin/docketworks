"""Form entry writes: row + one ProcessEvent, one transaction.

Mirrors forms_service's shape (see that module's docstring): the row write
and its audit event commit or roll back together, and update_form_entry's
diff loop skips unchanged values so a no-op PATCH writes no event.

Named create_form_entry/update_form_entry, not create_entry/update_entry:
apps.timesheet.services.workshop_timesheet_service already defines
create_entry/update_entry for an unrelated concept (workshop timesheet
lines), and scripts/checks/find_duplicates.py's collision check is
name-based with no per-domain exemption (ADR 0039).
"""

import logging
from datetime import date
from uuid import UUID

from django.db import transaction
from ninja.errors import HttpError

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.process.models import Form, FormEntry
from apps.process.schemas import EntryCreateIn, EntryUpdateIn
from apps.process.services.entry_validation import display_data, parse_schema, validate_entry_data
from apps.process.services.process_events import FieldChange, json_safe, record_entry_event

logger = logging.getLogger(__name__)


def _resolve_staff(staff_id: UUID | None) -> Staff | None:
    """Resolve a subject-staff UUID, or raise 400 naming the bad referent."""
    if staff_id is None:
        return None
    staff = Staff.objects.filter(pk=staff_id).first()
    if staff is None:
        raise HttpError(400, f"'staff' does not name an existing staff member: {staff_id}.")
    return staff


def _resolve_job(job_id: UUID | None) -> Job | None:
    """Resolve a linked-job UUID, or raise 400 naming the bad referent."""
    if job_id is None:
        return None
    job = Job.objects.filter(pk=job_id).first()
    if job is None:
        raise HttpError(400, f"'job' does not name an existing job: {job_id}.")
    return job


def _resolve_parent_entry(parent_id: UUID | None) -> FormEntry | None:
    """Resolve a parent-entry UUID, or raise 400 naming the bad referent."""
    if parent_id is None:
        return None
    parent = FormEntry.objects.filter(pk=parent_id).first()
    if parent is None:
        raise HttpError(400, f"'parent_entry' does not name an existing entry: {parent_id}.")
    return parent


def create_form_entry(*, staff: Staff, form: Form, payload: EntryCreateIn) -> FormEntry:
    """Create a form entry and its entry_created event.

    ``entered_by`` is always the authenticated caller; ``staff`` (the entry's
    subject, e.g. an inductee) is never invented and stays NULL when omitted.
    """
    validate_entry_data(form, payload.data)
    subject_staff = _resolve_staff(payload.staff)
    job = _resolve_job(payload.job)
    parent_entry = _resolve_parent_entry(payload.parent_entry)
    with transaction.atomic():
        entry = FormEntry.objects.create(
            form=form,
            entry_date=payload.entry_date,
            data=payload.data,
            staff=subject_staff,
            entered_by=staff,
            job=job,
            parent_entry=parent_entry,
        )
        record_entry_event(entry=entry, staff=staff, event_type="entry_created", changes=[])
    return entry


def _entry_changes(
    form: Form, before: dict[str, object], after: dict[str, object]
) -> list[FieldChange]:
    """Compute per-field changes with the schema's labels and display-resolved values.

    So the history panel reads 'Injured staff member changed from Ben to
    Ryan', never a UUID.
    """
    spec = parse_schema(form)
    labels = {field.key: field.label for field in spec.fields}
    before_display = display_data(form, before)
    after_display = display_data(form, after)
    changes: list[FieldChange] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        changes.append(
            {
                "field_name": labels.get(key, key),
                "old_value": str(before_display.get(key, json_safe(old))),
                "new_value": str(after_display.get(key, json_safe(new))),
            }
        )
    return changes


def _top_level_changes(
    entry: FormEntry,
    *,
    new_entry_date: date,
    new_staff: Staff | None,
    new_job: Job | None,
    new_parent: FormEntry | None,
) -> list[FieldChange]:
    """Compute changes on the entry's non-``data`` fields; staff is display-resolved."""
    changes: list[FieldChange] = []
    if new_entry_date != entry.entry_date:
        changes.append(
            {
                "field_name": "Entry Date",
                "old_value": str(json_safe(entry.entry_date)),
                "new_value": str(json_safe(new_entry_date)),
            }
        )
    if new_staff != entry.staff:
        changes.append(
            {
                "field_name": "Staff",
                "old_value": entry.staff.get_display_full_name() if entry.staff else "",
                "new_value": new_staff.get_display_full_name() if new_staff else "",
            }
        )
    if new_job != entry.job:
        changes.append(
            {
                "field_name": "Job",
                "old_value": str(entry.job) if entry.job else "",
                "new_value": str(new_job) if new_job else "",
            }
        )
    if new_parent != entry.parent_entry:
        changes.append(
            {
                "field_name": "Parent Entry",
                "old_value": str(entry.parent_entry_id) if entry.parent_entry_id else "",
                "new_value": str(new_parent.id) if new_parent else "",
            }
        )
    return changes


def update_form_entry(*, staff: Staff, entry: FormEntry, payload: EntryUpdateIn) -> FormEntry:
    """Apply only the fields the caller sent; write at most one event.

    ``data``, when sent, replaces the entry's data whole (the entry form
    always submits every field) — it is not merged key-by-key against the
    stored data, so a field the caller drops from the payload is dropped from
    the entry too. Referent UUIDs (``staff``/``job``/``parent_entry``) that
    match nothing are a transparent 400 naming the missing referent, resolved
    before anything is written.
    """
    supplied = payload.model_dump(exclude_unset=True)
    new_data = supplied.get("data", entry.data)
    validate_entry_data(entry.form, new_data)

    new_staff = _resolve_staff(supplied["staff"]) if "staff" in supplied else entry.staff
    new_job = _resolve_job(supplied["job"]) if "job" in supplied else entry.job
    new_parent = (
        _resolve_parent_entry(supplied["parent_entry"])
        if "parent_entry" in supplied
        else entry.parent_entry
    )
    new_entry_date = supplied.get("entry_date", entry.entry_date)

    changes = _entry_changes(entry.form, entry.data, new_data)
    changes.extend(
        _top_level_changes(
            entry,
            new_entry_date=new_entry_date,
            new_staff=new_staff,
            new_job=new_job,
            new_parent=new_parent,
        )
    )

    entry.entry_date = new_entry_date
    entry.data = new_data
    entry.staff = new_staff
    entry.job = new_job
    entry.parent_entry = new_parent

    with transaction.atomic():
        entry.save()
        if changes:
            record_entry_event(
                entry=entry, staff=staff, event_type="entry_updated", changes=changes
            )
    return entry


def archive_entry(*, staff: Staff, entry: FormEntry) -> None:
    """Soft-delete an entry (is_active=False) and write its entry_archived event."""
    with transaction.atomic():
        entry.is_active = False
        entry.save(update_fields=["is_active", "updated_at"])
        record_entry_event(entry=entry, staff=staff, event_type="entry_archived", changes=[])
