"""The category backfill assigns each document exactly one category from tags.

The rule is most-specific-first, so a doc tagged safety+incident lands in
incident (v1 listed it under both — the double-listing defect this field
exists to remove).
"""

from apps.process.migrations._0003_helpers import (
    form_category,
    procedure_category,
)


class TestFormCategory:
    def test_incident_beats_safety(self) -> None:
        assert form_category("form", ["safety", "incident"]) == "incident"

    def test_register_document_type_wins_over_safety_tags(self) -> None:
        assert form_category("register", ["safety", "hazard"]) == "register"

    def test_meeting_then_training_then_safety(self) -> None:
        assert form_category("form", ["meeting"]) == "meeting"
        assert form_category("form", ["training", "refresher"]) == "training"
        assert form_category("form", ["safety", "inspection"]) == "safety"

    def test_untagged_forms_default_to_safety(self) -> None:
        assert form_category("form", []) == "safety"


class TestProcedureCategory:
    def test_jsa_beats_safety(self) -> None:
        assert procedure_category("procedure", ["jsa", "safety"]) == "jsa"

    def test_reference_type_then_training_then_safety(self) -> None:
        assert procedure_category("reference", ["safety", "planning"]) == "reference"
        assert procedure_category("procedure", ["training"]) == "training"
        assert procedure_category("procedure", ["safety", "sop"]) == "safety"
