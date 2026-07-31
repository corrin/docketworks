import pytest

from apps.process.models import Form, FormEntry
from apps.process.services.form_service import FormService


def _make_service() -> FormService:
    """Create a FormService."""
    return FormService()


@pytest.mark.django_db
class TestFormServiceCreateEntry:
    def test_create_entry_returns_form_entry(self) -> None:
        form = Form.objects.create(
            document_type="form",
            title="Inspection Form",
            document_number="110",
            tags=["safety", "inspection"],
        )

        service = _make_service()
        entry = service.create_entry(form_id=form.pk)

        assert isinstance(entry, FormEntry)
        assert entry.form == form

    def test_create_entry_with_job(self, job):
        form = Form.objects.create(
            document_type="form",
            title="Incident Report",
        )

        service = _make_service()
        entry = service.create_entry(form_id=form.pk, job_id=job.pk)

        assert entry.job == job

    def test_create_entry_with_data(self) -> None:
        form = Form.objects.create(
            document_type="form",
            title="Checklist",
            form_schema={"fields": [{"key": "item", "type": "text"}]},
        )

        service = _make_service()
        entry = service.create_entry(
            form_id=form.pk,
            data={"item": "Ladder"},
        )

        assert entry.data == {"item": "Ladder"}


@pytest.mark.django_db
class TestFormServiceCreateForm:
    def test_create_form_happy_path(self) -> None:
        service = _make_service()
        doc = service.create_form(
            title="Inspection Checklist",
            document_type="form",
            tags=["safety", "inspection"],
            document_number="110",
            form_schema={"fields": [{"key": "item", "type": "text"}]},
        )

        assert doc.document_type == "form"
        assert doc.title == "Inspection Checklist"
        assert doc.tags == ["safety", "inspection"]
        assert doc.document_number == "110"
        assert doc.status == "active"
        assert doc.form_schema == {"fields": [{"key": "item", "type": "text"}]}

    def test_create_form_register_type(self) -> None:
        service = _make_service()
        doc = service.create_form(
            title="Chemical Register",
            document_type="register",
        )

        assert doc.document_type == "register"

    def test_create_form_rejects_procedure_type(self) -> None:
        service = _make_service()
        with pytest.raises(ValueError, match="form.*register"):
            service.create_form(
                title="Not a form",
                document_type="procedure",
            )
