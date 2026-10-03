"""Model-level contracts for the process domain.

Category is stored and exclusive (one home per document); entries link to a
parent entry (a meeting's actions and attendance sign-offs point back at the
minutes entry); actual entry edits advance their freshness timestamp.
"""

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry, Procedure
from apps.process.schemas import EntryUpdateIn
from apps.process.services.entries_service import update_form_entry

pytestmark = pytest.mark.django_db


def make_form(**overrides: object) -> Form:
    defaults: dict[str, object] = {
        "document_type": "form",
        "category": Form.Category.SAFETY,
        "title": "Site inspection",
        "form_schema": {"fields": []},
    }
    defaults.update(overrides)
    return Form.objects.create(**defaults)


class TestCategory:
    def test_form_categories_are_the_five_agreed_values(self) -> None:
        assert [choice[0] for choice in Form.Category.choices] == [
            "safety",
            "training",
            "incident",
            "meeting",
            "register",
        ]

    def test_procedure_categories_are_the_four_agreed_values(self) -> None:
        assert [choice[0] for choice in Procedure.Category.choices] == [
            "safety",
            "jsa",
            "training",
            "reference",
        ]


class TestFormEntryLinks:
    def test_an_entry_can_link_to_a_parent_entry_on_another_form(self) -> None:
        minutes_form = make_form(category=Form.Category.MEETING, title="Meeting minutes")
        actions_form = make_form(category=Form.Category.MEETING, title="Actions")
        minutes = FormEntry.objects.create(form=minutes_form, entry_date="2026-08-25", data={})
        action = FormEntry.objects.create(
            form=actions_form, entry_date="2026-08-25", data={}, parent_entry=minutes
        )
        assert list(minutes.child_entries.all()) == [action]

    def test_entries_carry_updated_at(self, office_staff: Staff) -> None:
        # GPT: A create-only timestamp check misses edits that leave freshness stale.
        with freeze_time("2026-08-25T08:00:00Z"):
            form = make_form(
                form_schema={"fields": [{"key": "area", "label": "Area", "type": "text"}]}
            )
            entry = FormEntry.objects.create(
                form=form, entry_date="2026-08-25", data={"area": "Bay 1"}
            )
            created_at = entry.updated_at

        with freeze_time("2026-08-25T09:00:00Z"):
            update_form_entry(
                staff=office_staff, entry=entry, payload=EntryUpdateIn(data={"area": "Bay 2"})
            )
            entry.refresh_from_db()
            assert entry.data == {"area": "Bay 2"}
            assert entry.updated_at == timezone.now()
            assert entry.updated_at > created_at
