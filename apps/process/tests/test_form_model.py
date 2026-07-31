import pytest

from apps.process.models import Form, FormEntry


@pytest.mark.django_db
class TestForm:
    def test_create_form_definition(self) -> None:
        form = Form.objects.create(
            document_type="form",
            title="Ladder Inspection Checklist",
            document_number="110",
            tags=["safety", "inspection"],
        )
        assert form.status == "active"
        assert form.document_type == "form"

    def test_filter_by_document_type(self) -> None:
        Form.objects.create(document_type="form", title="Form")
        Form.objects.create(document_type="register", title="Reg")
        assert Form.objects.filter(document_type="form").count() == 1
        assert Form.objects.filter(document_type="register").count() == 1

    def test_str_representation(self) -> None:
        doc = Form.objects.create(
            document_type="form",
            title="Safety Checklist",
        )
        assert "Form" in str(doc)
        assert "Safety Checklist" in str(doc)


@pytest.mark.django_db
class TestFormEntry:
    def test_create_entry(self) -> None:
        doc = Form.objects.create(
            document_type="register",
            title="Maintenance Log",
        )
        entry = FormEntry.objects.create(
            form=doc,
            entry_date="2026-03-03",
            data={
                "equipment": "Drill Press",
                "action": "Oiled bearings",
                "status": "OK",
            },
        )
        assert entry.form == doc
        assert entry.data["equipment"] == "Drill Press"
        assert doc.entries.count() == 1

    def test_entry_with_job(self, job):
        doc = Form.objects.create(
            document_type="form",
            title="Incident Report",
            tags=["incident"],
        )
        entry = FormEntry.objects.create(
            form=doc,
            job=job,
            entry_date="2026-03-03",
            data={"description": "test"},
        )
        assert entry.job == job
        assert job.form_entries.count() == 1

    def test_cascade_delete(self) -> None:
        doc = Form.objects.create(
            document_type="register",
            title="Maintenance Log",
        )
        FormEntry.objects.create(
            form=doc,
            entry_date="2026-03-03",
            data={"note": "test"},
        )
        doc.delete()
        assert FormEntry.objects.count() == 0
