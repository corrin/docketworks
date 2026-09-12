"""Give pre-2026-04-22 job events the detail their descriptions are built from.

Those events stored a rendered sentence under ``legacy_description`` instead of
the values behind it, so their descriptions could not be rebuilt like every
other event's. This reads each sentence back into the structured shape the
builders already use, and drops the stored text.

What cannot be recovered is recorded as absent rather than invented: a change
whose before and after were never written keeps its field name and no values, so
it renders as lost rather than as a change to empty. Creations recover their job
and company from the job row itself; their initial status and pricing
methodology are gone, because the job now holds what it was last changed to.

Parsing the sentence at read time was the alternative and is rejected — it would
leave every reader parsing English forever, which is the branch this removes.
"""

import re
from typing import Protocol

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

#: "Status changed from Recently Completed to Archived"
_TRANSITION = re.compile(r"^(?P<field>.+?) changed from (?P<old>.+?) to (?P<new>.+)$")
#: "Notes updated", "Job details updated", "Notes added", "Notes removed"
_FIELD_ONLY = re.compile(r"^(?P<field>.+?) (?:updated|added|removed)$")
#: "Quote acceptance date removed. Was previously accepted on 2025-09-19"
_ACCEPTANCE = re.compile(
    r"^Quote acceptance date removed\. Was previously accepted on (?P<old>.+)$"
)
#: "Invoice INV-55919 created"
_INVOICE = re.compile(r"^Invoice (?P<number>\S+) created$")


def _changes_from(sentence: str) -> list[dict[str, str]] | None:
    """Read one stored sentence into the change records the builders render."""
    acceptance = _ACCEPTANCE.match(sentence)
    if acceptance:
        return [
            {
                "field_name": "Quote acceptance date",
                "old_value": acceptance["old"],
                "new_value": "",
            }
        ]

    changes: list[dict[str, str]] = []
    # A few sentences record two changes joined by a comma.
    for clause in sentence.split(", "):
        transition = _TRANSITION.match(clause)
        if transition:
            changes.append(
                {
                    "field_name": transition["field"],
                    "old_value": transition["old"],
                    "new_value": transition["new"],
                }
            )
            continue
        field_only = _FIELD_ONLY.match(clause)
        if field_only:
            # No values: the writer of the day never recorded them.
            changes.append({"field_name": field_only["field"]})
            continue
        return None
    return changes or None


class _NamedRow(Protocol):
    """Anything carrying a display name — the job, or the company on it."""

    name: str


class _JobRow(Protocol):
    """The job an event points at, as the historical model exposes it."""

    name: str
    company: _NamedRow | None


class _EventRow(Protocol):
    """The fields of a job event this migration reads."""

    detail: dict[str, object]
    event_type: str
    job: _JobRow | None


def _restructured(event: _EventRow) -> dict[str, object]:
    """The detail this event should carry once its stored sentence is read back."""
    detail = dict(event.detail)
    sentence = str(detail.pop("legacy_description", "") or "").strip()
    event_type = event.event_type

    if event_type == "job_created":
        job = event.job
        if job is not None:
            detail.setdefault("job_name", job.name)
            if job.company is not None:
                detail.setdefault("company_name", job.company.name)
        return detail

    if event_type == "invoice_created":
        invoice = _INVOICE.match(sentence)
        if invoice:
            detail.setdefault("xero_invoice_number", invoice["number"])
        return detail

    if not detail.get("changes"):
        changes = _changes_from(sentence)
        if changes:
            detail["changes"] = changes
    return detail


def structure_stored_descriptions(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Rewrite every stored sentence into detail, then drop the sentence."""
    del schema_editor
    JobEvent = apps.get_model("job", "JobEvent")

    updated = []
    events = JobEvent.objects.filter(detail__has_key="legacy_description").select_related(
        "job", "job__company"
    )
    for event in events.iterator(chunk_size=500):
        event.detail = _restructured(event)
        updated.append(event)
        if len(updated) >= 500:
            JobEvent.objects.bulk_update(updated, ["detail"])
            updated.clear()
    if updated:
        JobEvent.objects.bulk_update(updated, ["detail"])


class Migration(migrations.Migration):
    dependencies = [("job", "0012_alter_costline_options")]
    operations = [
        migrations.RunPython(
            structure_stored_descriptions,
            # The stored sentence is the thing being removed; putting it back
            # would restore the branch that read it.
            reverse_code=migrations.RunPython.noop,
        ),
    ]
