"""ProcessEvent is the domain's one visible audit implementation.

An entry is a formal record ("Ben signed reading this on this date"); edits
are allowed for anyone authenticated, so the event log is the control — it
must say who changed what, when, in words a reader can use.
"""

import pytest

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry, ProcessEvent
from apps.process.services.process_events import record_entry_event

pytestmark = pytest.mark.django_db


def make_staff() -> Staff:
    return Staff.objects.create_user(
        office_email="auditor@example.com",
        password="s3cret-Pass!",
        first_name="Audrey",
        last_name="Auditor",
    )


def make_entry() -> FormEntry:
    form = Form.objects.create(
        document_type="form",
        category=Form.Category.SAFETY,
        title="Inspection",
        form_schema={"fields": [{"key": "area", "label": "Area", "type": "text"}]},
    )
    return FormEntry.objects.create(form=form, entry_date="2026-08-25", data={"area": "Bay 1"})


class TestRecordEntryEvent:
    def test_writes_one_event_with_deltas_and_changes(self) -> None:
        entry = make_entry()
        event = record_entry_event(
            entry=entry,
            staff=make_staff(),
            event_type="entry_updated",
            changes=[{"field_name": "Area", "old_value": "Bay 1", "new_value": "Bay 2"}],
            before={"data": {"area": "Bay 1"}},
            after={"data": {"area": "Bay 2"}},
        )
        assert ProcessEvent.objects.count() == 1
        assert event.form_entry == entry
        assert event.delta_before == {"data": {"area": "Bay 1"}}
        assert event.description == "Area changed from 'Bay 1' to 'Bay 2'"

    def test_created_event_describes_itself(self) -> None:
        entry = make_entry()
        event = record_entry_event(
            entry=entry, staff=make_staff(), event_type="entry_created", changes=[]
        )
        assert event.description == "Entry created"

    def test_events_cascade_with_their_entry(self) -> None:
        entry = make_entry()
        record_entry_event(entry=entry, staff=make_staff(), event_type="entry_created", changes=[])
        entry.delete()
        assert ProcessEvent.objects.count() == 0
