"""API tests for the procedure endpoints."""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.process.models import Procedure


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
class TestProcedureAPI:
    def test_list_safety_procedures(self, api_client):
        Procedure.objects.create(
            document_type="procedure",
            title="Drill Press SOP",
            tags=["safety", "sop"],
        )

        resp = api_client.get("/api/process/procedures/safety/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["title"] == "Drill Press SOP"

    def test_list_training_procedures(self, api_client):
        Procedure.objects.create(
            document_type="procedure",
            title="Induction Plan",
            tags=["training"],
        )
        Procedure.objects.create(
            document_type="procedure",
            title="Safety SOP",
            tags=["safety"],
        )

        resp = api_client.get("/api/process/procedures/training/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["title"] == "Induction Plan"

    def test_list_reference_procedures(self, api_client):
        Procedure.objects.create(
            document_type="reference",
            title="Org Chart",
            tags=[],
        )

        resp = api_client.get("/api/process/procedures/reference/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["title"] == "Org Chart"

    def test_detail_has_google_doc_fields(self, api_client):
        doc = Procedure.objects.create(
            document_type="procedure",
            title="SWP",
            tags=["safety", "swp"],
        )

        resp = api_client.get(f"/api/process/procedures/safety/{doc.pk}/")
        assert resp.status_code == status.HTTP_200_OK
        assert "form_schema" not in resp.data
        assert "google_doc_url" in resp.data
        assert "google_doc_id" in resp.data

    def test_unknown_category_returns_404(self, api_client):
        resp = api_client.get("/api/process/procedures/nonexistent/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_list_excludes_form_schema(self, api_client):
        Procedure.objects.create(
            document_type="procedure",
            title="SWP",
            tags=["safety"],
        )

        resp = api_client.get("/api/process/procedures/safety/")
        assert resp.status_code == status.HTTP_200_OK
        assert "form_schema" not in resp.data[0]
        assert "google_doc_url" in resp.data[0]

    def test_filter_by_tags(self, api_client):
        Procedure.objects.create(
            document_type="procedure",
            title="SWP1",
            tags=["safety", "swp"],
        )
        Procedure.objects.create(
            document_type="procedure",
            title="SOP1",
            tags=["safety", "sop"],
        )

        resp = api_client.get("/api/process/procedures/safety/?tags=swp")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["title"] == "SWP1"

    @patch("apps.process.services.procedure_service.ProcedureService")
    def test_create_procedure(self, MockService, api_client):
        doc = Procedure.objects.create(
            document_type="procedure",
            title="New SWP",
            tags=["safety"],
            status="draft",
        )
        MockService.return_value.create_blank_procedure.return_value = doc

        resp = api_client.post(
            "/api/process/procedures/safety/",
            {"title": "New SWP"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["title"] == "New SWP"
        MockService.return_value.create_blank_procedure.assert_called_once()

    def test_update_procedure(self, api_client):
        doc = Procedure.objects.create(
            document_type="procedure",
            title="Old Title",
            tags=["safety"],
        )

        resp = api_client.patch(
            f"/api/process/procedures/safety/{doc.pk}/",
            {"title": "New Title"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["title"] == "New Title"

    def test_delete_procedure(self, api_client):
        doc = Procedure.objects.create(
            document_type="procedure",
            title="To Delete",
            tags=["safety"],
        )

        resp = api_client.delete(f"/api/process/procedures/safety/{doc.pk}/")
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Procedure.objects.filter(pk=doc.pk).exists()


@pytest.mark.django_db
class TestRemovedEndpoints:
    def test_process_documents_endpoint_removed(self, api_client):
        resp = api_client.get("/api/process/process-documents/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_sop_list_endpoint_removed(self, api_client):
        resp = api_client.get("/api/process/sop/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_swp_list_endpoint_removed(self, api_client):
        resp = api_client.get("/api/process/swp/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
