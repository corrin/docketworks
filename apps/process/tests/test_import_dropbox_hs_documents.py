"""The import_dropbox_hs_documents command: discovery, mapping, refusals, uploads.

The Google seams (the shared delegated-credentials builder and the Drive
client factory) are faked where the command bound them at import; the folder tree is real
files under tmp_path, so discovery, skip rules and duplicate resolution all
run for real.
"""

import os
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import AppError, CompanyDefaults
from apps.process.management.commands import import_dropbox_hs_documents as import_module
from apps.process.management.commands.import_dropbox_hs_documents import (
    DOC_MAPPING,
    FORM_SCHEMAS,
)
from apps.process.migrations._0003_helpers import (
    form_category,
    procedure_category,
)
from apps.process.models import Form, Procedure

pytestmark = pytest.mark.django_db

# Every fixture document is stamped with this, so the timestamp assertions can
# be literals. Re-deriving the expectation from stat() — which is what these
# tests used to do — passes whatever the code reads and whichever field the
# platform happens to fill, so it cannot fail.
SOURCE_MTIME = datetime(2019, 3, 14, 9, 26, 53, tzinfo=UTC)


def _run(*args: str) -> str:
    out = StringIO()
    call_command("import_dropbox_hs_documents", *args, stdout=out)
    return out.getvalue()


def _write_doc(folder: Path, name: str) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"doc-bytes")
    os.utime(path, (SOURCE_MTIME.timestamp(), SOURCE_MTIME.timestamp()))
    return path


def _configure_upload_prereqs() -> None:
    defaults = CompanyDefaults.get_solo()
    defaults.gdrive_reference_library_folder_id = "folder-1"
    defaults.company_email = "office@example.test"
    defaults.save(update_fields=["gdrive_reference_library_folder_id", "company_email"])


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub the Google seams; returns the Drive service mock."""
    drive_service = MagicMock()
    drive_service.files.return_value.create.return_value.execute.return_value = {"id": "gdoc-1"}
    monkeypatch.setenv("GCP_CREDENTIALS", "/keys/service-account.json")
    monkeypatch.setattr(import_module, "delegated_credentials", MagicMock())
    monkeypatch.setattr(import_module, "build", MagicMock(return_value=drive_service))
    return drive_service


class TestRefusals:
    """Upload prerequisites are validated upfront, before any file is touched."""

    def test_missing_folder_is_refused_and_persisted(self, tmp_path: Path) -> None:
        with pytest.raises(CommandError, match="Folder does not exist"):
            _run("--folder", str(tmp_path / "nope"), "--dry-run")
        # handle() persists every failure with its context before re-raising.
        assert AppError.objects.count() == 1

    def test_non_directory_path_is_refused(self, tmp_path: Path) -> None:
        file_path = _write_doc(tmp_path, "Doc.100 Policy.doc")

        with pytest.raises(CommandError, match="Path is not a directory"):
            _run("--folder", str(file_path), "--dry-run")

    def test_real_import_requires_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GCP_CREDENTIALS", raising=False)

        with pytest.raises(CommandError, match="GCP_CREDENTIALS is not set"):
            _run("--folder", str(tmp_path))

    def test_real_import_requires_reference_folder_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GCP_CREDENTIALS", "/keys/service-account.json")

        with pytest.raises(
            CommandError, match="gdrive_reference_library_folder_id is not configured"
        ):
            _run("--folder", str(tmp_path))

    def test_real_import_requires_an_impersonation_subject(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GCP_CREDENTIALS", "/keys/service-account.json")
        monkeypatch.delenv("GCP_DELEGATED_SUBJECT", raising=False)
        defaults = CompanyDefaults.get_solo()
        defaults.gdrive_reference_library_folder_id = "folder-1"
        defaults.save(update_fields=["gdrive_reference_library_folder_id"])

        with pytest.raises(CommandError, match="No impersonation subject"):
            _run("--folder", str(tmp_path))


class TestDryRun:
    """A dry run previews the mapping and creates and uploads nothing."""

    def test_previews_mapping_without_creating_records(self, tmp_path: Path) -> None:
        _write_doc(tmp_path, "Doc.100 Health and Safety Policy.docx")
        _write_doc(tmp_path, "Section 1/Doc.108 Maintenance Request.doc")
        _write_doc(tmp_path, "Doc.999 Mystery.doc")
        _write_doc(tmp_path, "notes.doc")  # no Doc.NNN pattern
        _write_doc(tmp_path, "Doc.101 Policy.txt")  # not a Word document
        _write_doc(tmp_path, "zPauls Folder/Doc.102 Old Plan.doc")
        _write_doc(tmp_path, "Archive/Doc.103 Older Plan.doc")

        output = _run("--folder", str(tmp_path), "--dry-run")

        assert "Would import 2 documents, skipped 0 (already exist), skipped 1 (no mapping)" in (
            output
        )
        assert '[GDOC] Doc.100 "Health and Safety Policy" -> procedure' in output
        assert '[FORM] Doc.108 "Maintenance Request" -> form' in output
        assert 'Skipped Doc.999 "Mystery" (no mapping)' in output
        assert "Doc.102" not in output
        assert "Doc.103" not in output
        assert Procedure.objects.count() == 0
        assert Form.objects.count() == 0

    def test_dry_run_needs_no_credentials_or_configuration(self, tmp_path: Path) -> None:
        _write_doc(tmp_path, "Doc.100 Policy.doc")

        output = _run("--folder", str(tmp_path), "--dry-run")

        assert "Would import 1 documents" in output

    def test_filename_without_title_falls_back_to_document_number(self, tmp_path: Path) -> None:
        _write_doc(tmp_path, "Doc.105.docx")

        output = _run("--folder", str(tmp_path), "--dry-run")

        assert '"Document 105"' in output


@pytest.mark.usefixtures("drive")
class TestImport:
    """Real imports: Form rows are Django-only; prose docs upload to Drive."""

    def test_form_and_register_rows_are_created_without_google(
        self, tmp_path: Path, drive: MagicMock
    ) -> None:
        _configure_upload_prereqs()
        _write_doc(tmp_path, "Doc.108 Maintenance Request.doc")
        _write_doc(tmp_path, "Doc.380 Hazard Register.doc")

        output = _run("--folder", str(tmp_path))

        assert "Imported 2 documents, skipped 0 (already exist), skipped 0 (no mapping)" in output
        form = Form.objects.get(document_number="108")
        assert form.document_type == "form"
        assert form.title == "Maintenance Request"
        assert form.category == "safety"
        assert form.tags == ["safety", "inspection"]
        assert form.form_schema == FORM_SCHEMAS["108"]
        assert form.status == "active"
        # created_at is backdated to the source file's last-modified time,
        # which is what Dropbox preserves across a sync.
        assert form.created_at == SOURCE_MTIME
        register = Form.objects.get(document_number="380")
        assert register.document_type == "register"
        assert register.category == "register"
        assert register.form_schema == {}
        drive.files.assert_not_called()

    def test_prose_document_uploads_and_creates_procedure(
        self, tmp_path: Path, drive: MagicMock
    ) -> None:
        _configure_upload_prereqs()
        _write_doc(tmp_path, "Doc.100 Health and Safety Policy.doc")

        output = _run("--folder", str(tmp_path))

        assert "Imported 1 documents" in output
        procedure = Procedure.objects.get(document_number="100")
        assert procedure.document_type == "procedure"
        assert procedure.category == "safety"
        assert procedure.tags == ["safety", "policy"]
        assert procedure.google_doc_id == "gdoc-1"
        assert procedure.google_doc_url == "https://docs.google.com/document/d/gdoc-1/edit"
        assert procedure.created_at == SOURCE_MTIME
        create_kwargs = drive.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["name"] == "Doc.100 Health and Safety Policy"
        assert create_kwargs["body"]["parents"] == ["folder-1"]
        assert create_kwargs["body"]["mimeType"] == "application/vnd.google-apps.document"
        # No createdTime: the only local candidate is st_ctime, which is the
        # inode-change time, so sending it would assert a false creation date.
        assert "createdTime" not in create_kwargs["body"]
        # Conversion uploads ignore modifiedTime, so a second call restores it.
        update_kwargs = drive.files.return_value.update.call_args.kwargs
        assert update_kwargs["fileId"] == "gdoc-1"
        assert update_kwargs["body"] == {"modifiedTime": SOURCE_MTIME.isoformat()}

    def test_existing_document_numbers_are_skipped_never_updated(
        self, tmp_path: Path, drive: MagicMock
    ) -> None:
        _configure_upload_prereqs()
        Form.objects.create(document_type="form", title="Original", document_number="108")
        Procedure.objects.create(document_type="procedure", title="Original", document_number="100")
        _write_doc(tmp_path, "Doc.108 Maintenance Request.doc")
        _write_doc(tmp_path, "Doc.100 Health and Safety Policy.doc")

        output = _run("--folder", str(tmp_path))

        assert "Imported 0 documents, skipped 2 (already exist), skipped 0 (no mapping)" in output
        assert Form.objects.get(document_number="108").title == "Original"
        assert Procedure.objects.get(document_number="100").title == "Original"
        drive.files.assert_not_called()

    def test_duplicate_files_resolve_to_doc_over_newer_docx(self, tmp_path: Path) -> None:
        _configure_upload_prereqs()
        doc_file = _write_doc(tmp_path, "Doc.100 Kept Policy.doc")
        docx_file = _write_doc(tmp_path, "Doc.100 Superseded Policy.docx")
        # The .docx is strictly newer, proving the preference is by extension.
        base = doc_file.stat().st_mtime
        os.utime(docx_file, (base + 3600, base + 3600))

        output = _run("--folder", str(tmp_path))

        assert "Imported 1 documents" in output
        assert Procedure.objects.count() == 1
        assert Procedure.objects.get(document_number="100").title == "Kept Policy"


class TestDocMappingCategoriesMatchTheRule:
    """DOC_MAPPING's category is hand-derived; this proves it agrees with the rule.

    One implementation decides category (apps/process/migrations/
    _0003_helpers.py); DOC_MAPPING only records what that rule produces for
    each row's stored type+tags, so this is the check that the two never
    drift apart.
    """

    def test_every_row_category_equals_the_rule_derivation(self) -> None:
        for doc_number, (doc_type, category, tags) in DOC_MAPPING.items():
            expected = (
                form_category(doc_type, tags)
                if doc_type in ("form", "register")
                else procedure_category(doc_type, tags)
            )
            assert category == expected, (
                f"Doc.{doc_number}: mapping says {category!r} but the rule "
                f"derives {expected!r} from ({doc_type!r}, {tags!r})"
            )
