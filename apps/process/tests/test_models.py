"""Model-level contracts for the process domain.

Category is stored and exclusive (one home per document); entries link to a
parent entry (a meeting's actions and attendance sign-offs point back at the
minutes entry); simple-history is gone because ProcessEvent is the one audit
implementation.
"""

import pytest

from apps.process.models import Form, FormEntry, Procedure

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

    def test_entries_carry_updated_at(self) -> None:
        entry = FormEntry.objects.create(form=make_form(), entry_date="2026-08-25", data={})
        assert entry.updated_at is not None


class TestSimpleHistoryIsGone:
    def test_no_history_manager_on_any_process_model(self) -> None:
        for model in (Form, FormEntry, Procedure):
            assert not hasattr(model, "history")
