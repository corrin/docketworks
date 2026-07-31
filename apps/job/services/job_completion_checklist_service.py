"""Reads and partial updates for the Job completion checklist.

Every accepted change writes one job-history event naming the item, its old and
new value, the acting staff member and the time, so a withdrawn confirmation is
as visible as a granted one.
"""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.job_completion_checklist import JobCompletionChecklist
from apps.job.models.job_event import JobEvent

CHECKLIST_UPDATED_EVENT = "completion_checklist_updated"


class ChecklistUpdateError(ValueError):
    """Raised when a checklist update names an unknown item or a non-boolean."""


def get_completion_checklist(job: Job) -> JobCompletionChecklist:
    """The job's checklist.

    A job nobody has confirmed anything on gets an unsaved all-false checklist
    rather than a row written during a read.
    """
    checklist = JobCompletionChecklist.objects.filter(job=job).first()
    if not checklist:
        return JobCompletionChecklist(job=job)
    else:
        return checklist


def update_completion_checklist(
    job: Job, updates: dict[str, bool], staff: Staff
) -> JobCompletionChecklist:
    """Apply a partial checklist update and audit each item that changed.

    Raises ChecklistUpdateError for unknown item keys or non-boolean values, so a
    typo in a client payload is a 400 rather than a silently ignored field.
    """
    unknown = sorted(set(updates) - set(JobCompletionChecklist.ITEM_FIELDS))
    if unknown:
        raise ChecklistUpdateError(
            f"Unknown checklist item(s): {', '.join(unknown)}. "
            f"Valid items: {', '.join(JobCompletionChecklist.ITEM_FIELDS)}."
        )

    non_boolean = sorted(
        key for key, value in updates.items() if not isinstance(value, bool)
    )
    if non_boolean:
        raise ChecklistUpdateError(
            f"Checklist item(s) must be true or false: {', '.join(non_boolean)}."
        )

    with transaction.atomic():
        checklist, _ = JobCompletionChecklist.objects.get_or_create(job=job)

        changed = {
            key: value
            for key, value in updates.items()
            if getattr(checklist, key) != value
        }
        if not changed:
            return checklist

        for key, new_value in changed.items():
            _record_change(job, staff, key, getattr(checklist, key), new_value)
            setattr(checklist, key, new_value)

        checklist.updated_at = timezone.now()
        checklist.updated_by = staff
        checklist.save()

    return checklist


def _record_change(
    job: Job, staff: Staff, item: str, old_value: bool, new_value: bool
) -> None:
    JobEvent.objects.create(
        job=job,
        staff=staff,
        event_type=CHECKLIST_UPDATED_EVENT,
        detail={
            "changes": [
                {
                    "field_name": JobCompletionChecklist.ITEM_LABELS[item],
                    "old_value": "Yes" if old_value else "No",
                    "new_value": "Yes" if new_value else "No",
                }
            ]
        },
    )
