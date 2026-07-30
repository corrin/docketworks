import pytest

from apps.process.models import Procedure


@pytest.mark.django_db
class TestProcedure:
    def test_create_procedure_with_tags(self) -> None:
        doc = Procedure.objects.create(
            document_type="procedure",
            title="Drill Press SOP",
            document_number="355",
            tags=["safety", "sop", "machinery"],
        )
        assert doc.document_type == "procedure"
        assert "sop" in doc.tags
        assert doc.status == "active"

    def test_filter_by_tags_contains(self) -> None:
        Procedure.objects.create(
            document_type="procedure",
            title="SWP1",
            tags=["safety", "swp"],
        )
        Procedure.objects.create(
            document_type="procedure",
            title="SOP1",
            tags=["sop"],
        )
        swps = Procedure.objects.filter(tags__contains=["swp"])
        assert swps.count() == 1
        assert swps.first().title == "SWP1"

    def test_filter_by_document_type(self) -> None:
        Procedure.objects.create(document_type="procedure", title="Proc")
        Procedure.objects.create(document_type="reference", title="Ref")
        assert Procedure.objects.filter(document_type="procedure").count() == 1
        assert Procedure.objects.filter(document_type="reference").count() == 1

    def test_str_representation(self) -> None:
        doc = Procedure.objects.create(
            document_type="procedure",
            title="MIG Welding",
        )
        assert "Procedure" in str(doc)
        assert "MIG Welding" in str(doc)
