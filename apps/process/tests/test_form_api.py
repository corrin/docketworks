"""API tests for the form endpoints."""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.process.models import Form


@pytest.fixture
def staff_user(db):
    return Staff.objects.create_user(
        email="worker@test.com",
        password="testpass123",
        first_name="Test",
        last_name="Worker",
        is_office_staff=True,
    )


@pytest.fixture
def api_client(staff_user):
    client = APIClient()
    client.force_authenticate(user=staff_user)
    return client


@pytest.mark.django_db
class TestFormAPI:
    def test_list_safety_forms(self, api_client):
        Form.objects.create(
            document_type="form",
            title="Ladder Inspection",
            tags=["safety", "inspection"],
        )

        resp = api_client.get("/api/process/forms/safety/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["title"] == "Ladder Inspection"

    def test_list_training_forms(self, api_client):
        Form.objects.create(
            document_type="form",
            title="Training Record",
            tags=["training"],
        )

        resp = api_client.get("/api/process/forms/training/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1

    def test_list_incident_forms(self, api_client):
        Form.objects.create(
            document_type="form",
            title="Incident Report",
            tags=["incident"],
        )

        resp = api_client.get("/api/process/forms/incident/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1

    def test_list_meeting_forms(self, api_client):
        Form.objects.create(
            document_type="form",
            title="Meeting Agenda",
            tags=["meeting"],
        )
        Form.objects.create(
            document_type="form",
            title="Admin Form",
            tags=["administration"],
        )

        resp = api_client.get("/api/process/forms/meeting/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2

    def test_list_registers(self, api_client):
        Form.objects.create(
            document_type="register",
            title="Chemical Register",
            tags=[],
        )

        resp = api_client.get("/api/process/forms/register/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1

    def test_detail_excludes_google_doc_fields(self, api_client):
        doc = Form.objects.create(
            document_type="form",
            title="Checklist",
            tags=["safety"],
            form_schema={"fields": [{"key": "item", "type": "text"}]},
        )

        resp = api_client.get(f"/api/process/forms/safety/{doc.pk}/")
        assert resp.status_code == status.HTTP_200_OK
        assert "form_schema" in resp.data
        assert "google_doc_url" not in resp.data
        assert "google_doc_id" not in resp.data

    def test_unknown_category_returns_404(self, api_client):
        resp = api_client.get("/api/process/forms/nonexistent/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_entry_allowed_for_form_document(self, api_client):
        doc = Form.objects.create(
            document_type="form",
            title="Checklist",
            tags=["safety"],
        )

        resp = api_client.post(
            f"/api/process/forms/safety/{doc.pk}/entries/",
            {"entry_date": "2026-03-07", "data": {"note": "test"}},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    def test_entry_allowed_for_register_document(self, api_client):
        doc = Form.objects.create(
            document_type="register",
            title="Chemical Register",
            tags=[],
        )

        resp = api_client.post(
            f"/api/process/forms/register/{doc.pk}/entries/",
            {"entry_date": "2026-03-07", "data": {"chemical": "acetone"}},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    @patch("apps.process.services.form_service.FormService")
    def test_create_form(self, MockService, api_client):
        doc = Form.objects.create(
            document_type="form",
            title="New Checklist",
            tags=["safety"],
            status="active",
            form_schema={"fields": [{"key": "item", "type": "text"}]},
        )
        MockService.return_value.create_form.return_value = doc

        resp = api_client.post(
            "/api/process/forms/safety/",
            {
                "title": "New Checklist",
                "form_schema": {"fields": [{"key": "item", "type": "text"}]},
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["title"] == "New Checklist"
        assert resp.data["form_schema"] == {"fields": [{"key": "item", "type": "text"}]}
        MockService.return_value.create_form.assert_called_once()

    def test_update_form(self, api_client):
        doc = Form.objects.create(
            document_type="form",
            title="Old Form",
            tags=["safety"],
        )

        resp = api_client.patch(
            f"/api/process/forms/safety/{doc.pk}/",
            {"title": "Updated Form"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["title"] == "Updated Form"

    def test_delete_form(self, api_client):
        doc = Form.objects.create(
            document_type="form",
            title="To Delete",
            tags=["safety"],
        )

        resp = api_client.delete(f"/api/process/forms/safety/{doc.pk}/")
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Form.objects.filter(pk=doc.pk).exists()

    def test_fill_creates_entry(self, api_client):
        form = Form.objects.create(
            document_type="form",
            title="Inspection Form",
            tags=["safety"],
        )

        resp = api_client.post(
            f"/api/process/forms/safety/{form.pk}/fill/",
            {"data": {"item": "Ladder"}},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert str(resp.data["form"]) == str(form.pk)
