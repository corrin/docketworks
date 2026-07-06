from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.company.models import Company
from apps.process.services.google_docs_service import GoogleDocResult
from apps.process.services.procedure_service import ProcedureService
from apps.workflow.models import CompanyDefaults


def _make_service():
    """Create a ProcedureService with external dependencies mocked out."""
    with (
        patch("apps.process.services.procedure_service.SafetyAIService"),
        patch("apps.process.services.procedure_service.GoogleDocsService"),
    ):
        service = ProcedureService()
    service.docs_service = MagicMock()
    return service


def _create_shop_client(name: str = "Shop Company") -> Company:
    return Company.objects.create(name=name, xero_last_modified=timezone.now())


@pytest.mark.django_db
class TestProcedureServiceCreateBlank:
    def test_create_blank_procedure_happy_path(self):
        CompanyDefaults.objects.create(
            company_name="Morris Sheetmetal",
            gdrive_reference_library_folder_id="folder-123",
            shop_company=_create_shop_client(),
        )

        service = _make_service()
        service.docs_service.create_blank_in_folder.return_value = GoogleDocResult(
            document_id="new-doc-id",
            edit_url="https://docs.google.com/document/d/new-doc-id/edit",
        )

        doc = service.create_blank_procedure(
            document_type="procedure",
            title="How to weld",
            tags=["welding", "safety"],
            document_number="301",
            site_location="Workshop",
        )

        assert doc.document_type == "procedure"
        assert doc.title == "How to weld"
        assert doc.tags == ["welding", "safety"]
        assert doc.document_number == "301"
        assert doc.site_location == "Workshop"
        assert doc.status == "draft"
        assert doc.google_doc_id == "new-doc-id"
        assert (
            doc.google_doc_url == "https://docs.google.com/document/d/new-doc-id/edit"
        )
        service.docs_service.create_blank_in_folder.assert_called_once_with(
            title="How to weld", folder_id="folder-123"
        )

    def test_create_blank_procedure_rejects_invalid_type(self):
        service = _make_service()
        with pytest.raises(ValueError, match="Invalid document_type"):
            service.create_blank_procedure(
                document_type="invalid",
                title="Bad type",
            )

    def test_create_blank_procedure_rejects_missing_folder_config(self):
        CompanyDefaults.objects.create(
            company_name="Test",
            gdrive_reference_library_folder_id="",
            shop_company=_create_shop_client(),
        )

        service = _make_service()
        with pytest.raises(ValueError, match="gdrive_reference_library_folder_id"):
            service.create_blank_procedure(
                document_type="procedure",
                title="No folder",
            )
