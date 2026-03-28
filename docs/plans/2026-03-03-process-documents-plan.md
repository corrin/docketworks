# Process Documents Migration - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename SafetyDocument to ProcessDocument, expand document types, add template/record workflow, and migrate ~80 Dropbox H&S documents into the app backed by Google Docs.

**Architecture:** Expand the existing SafetyDocument model into a general-purpose ProcessDocument with four types (procedure, form, register, reference), free-text tags, template/record workflow, and a generic ProcessDocumentEntry model for structured form data. All existing JSA/SWP/SOP functionality preserved via tag filtering.

**Tech Stack:** Django 6, DRF, Google Docs/Drive API, PostgreSQL, Vue 3 frontend (in `frontend/`)

---

### Task 1: Rename model SafetyDocument → ProcessDocument

**Files:**
- Modify: `apps/job/models/safety_document.py` → rename to `apps/job/models/process_document.py`
- Create: `apps/job/migrations/0070_rename_safetydocument_to_processdocument.py`

**Step 1: Rename the model file**

```bash
mv apps/job/models/safety_document.py apps/job/models/process_document.py
```

**Step 2: Update the model class**

In `apps/job/models/process_document.py`:
- Rename class `SafetyDocument` → `ProcessDocument`
- Keep `db_table = "workflow_safetydocument"` (avoid table rename)
- Update `verbose_name` to `"Process Document"`
- Update `related_name` on job FK to `"process_documents"`
- Update `__str__` and docstrings

**Step 3: Regenerate `__init__.py`**

```bash
python scripts/update_init.py
```

Verify it now exports `ProcessDocument` instead of `SafetyDocument`.

**Step 4: Update all imports project-wide**

Find and replace all references:
- `from apps.job.models import SafetyDocument` → `from apps.job.models import ProcessDocument`
- `from apps.job.models.safety_document import SafetyDocument` → `from apps.job.models.process_document import ProcessDocument`
- Variable names `safety_document` → `process_document` where appropriate

Files to update:
- `apps/job/services/safety_document_service.py`
- `apps/job/services/google_docs_service.py`
- `apps/job/serializers/safety_document_serializer.py`
- `apps/job/views/safety_viewsets.py`
- `apps/job/urls_rest.py`
- Any tests referencing SafetyDocument

**Step 5: Create migration**

```bash
python manage.py makemigrations job --name rename_safetydocument_to_processdocument
```

This should generate a `RenameModel` operation. Verify it does NOT rename the table (since we kept `db_table`).

**Step 6: Run migration and verify**

```bash
python manage.py migrate
python manage.py test apps.job --verbosity=2
```

**Step 7: Commit**

```bash
git add -A
git commit -m "refactor: rename SafetyDocument to ProcessDocument

Keep db_table unchanged to avoid table rename. All imports and
references updated project-wide."
```

---

### Task 2: Expand document_type choices and add new fields

**Files:**
- Modify: `apps/job/models/process_document.py`
- Create: `apps/job/migrations/0071_processdocument_expand_fields.py`

**Step 1: Update the model**

In `apps/job/models/process_document.py`, make these changes:

Change `DOCUMENT_TYPES` to:
```python
DOCUMENT_TYPES = [
    ("procedure", "Procedure"),
    ("form", "Form"),
    ("register", "Register"),
    ("reference", "Reference"),
]
```

Change `document_type` field:
```python
document_type = models.CharField(
    max_length=20,
    choices=DOCUMENT_TYPES,
    help_text="Document type: procedure, form, register, or reference",
)
```

Add new fields:
```python
# Classification
tags = models.JSONField(
    default=list,
    blank=True,
    help_text='Free-text tags, e.g. ["safety", "machinery", "sop"]',
)

# Template/record workflow
is_template = models.BooleanField(
    default=False,
    help_text="True if this is a template that can be filled in to create records",
)
status = models.CharField(
    max_length=20,
    choices=[
        ("draft", "Draft"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    ],
    default="active",
    help_text="Document lifecycle status",
)
parent_template = models.ForeignKey(
    "self",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="completed_records",
    help_text="Template this record was created from",
)
```

**Step 2: Write data migration for existing records**

Create a manual migration that maps old types to new types + tags:

```python
def migrate_document_types(apps, schema_editor):
    ProcessDocument = apps.get_model("job", "ProcessDocument")

    type_mapping = {
        "jsa": ("form", ["safety", "jsa"]),
        "swp": ("procedure", ["safety", "swp"]),
        "sop": ("procedure", ["sop"]),
    }

    for old_type, (new_type, tags) in type_mapping.items():
        ProcessDocument.objects.filter(document_type=old_type).update(
            document_type=new_type,
            tags=tags,
            status="active",
        )
```

**Step 3: Run migrations and verify**

```bash
python manage.py makemigrations job --name processdocument_expand_fields
# Then add the data migration function to the generated migration
python manage.py migrate
python manage.py test apps.job --verbosity=2
```

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: expand ProcessDocument with types, tags, template workflow

Add document types (procedure/form/register/reference), free-text tags,
is_template, status, and parent_template fields. Migrate existing
jsa/swp/sop records to new type system."
```

---

### Task 3: Create ProcessDocumentEntry model

**Files:**
- Create: `apps/job/models/process_document_entry.py`
- Modify: `apps/job/models/__init__.py` (regenerate)

**Step 1: Create the model**

Create `apps/job/models/process_document_entry.py`:

```python
"""
ProcessDocumentEntry - generic line entries for structured forms and registers.

Used for documents where content is structured data (inspections, logs, checklists)
rather than prose (which lives in Google Docs).
"""

import uuid

from django.db import models


class ProcessDocumentEntry(models.Model):
    """
    A single entry/line in a structured process document.

    The `data` JSON field schema varies by document type. Each form type
    defines its own expected fields.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document = models.ForeignKey(
        "ProcessDocument",
        related_name="entries",
        on_delete=models.CASCADE,
        help_text="Parent process document",
    )

    entry_date = models.DateField(
        help_text="Date this entry relates to",
    )

    entered_by = models.ForeignKey(
        "accounts.Staff",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Staff member who created this entry",
    )

    data = models.JSONField(
        default=dict,
        help_text="Entry data - schema varies by document type",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workflow_processdocumententry"
        ordering = ["-entry_date", "-created_at"]
        verbose_name = "Process Document Entry"
        verbose_name_plural = "Process Document Entries"

    def __str__(self):
        return f"Entry {self.entry_date} on {self.document.title}"
```

**Step 2: Regenerate `__init__.py` and create migration**

```bash
python scripts/update_init.py
python manage.py makemigrations job --name add_processdocumententry
python manage.py migrate
python manage.py test apps.job --verbosity=2
```

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: add ProcessDocumentEntry for structured form data

Generic entry model with JSON data field for line-entry forms
(maintenance logs, inspection checklists, training records).
Specific models can be added later when strong querying is needed."
```

---

### Task 4: Update serializers

**Files:**
- Rename: `apps/job/serializers/safety_document_serializer.py` → `apps/job/serializers/process_document_serializer.py`

**Step 1: Rename file and update serializers**

```bash
mv apps/job/serializers/safety_document_serializer.py apps/job/serializers/process_document_serializer.py
```

Update the file with:
- Rename `SafetyDocumentSerializer` → `ProcessDocumentSerializer`
- Rename `SafetyDocumentListSerializer` → `ProcessDocumentListSerializer`
- Add `tags`, `is_template`, `status`, `parent_template` fields
- Add `ProcessDocumentEntrySerializer`
- Keep `SWPGenerateRequestSerializer` as-is (still used by existing endpoints)

New fields on `ProcessDocumentSerializer`:
```python
tags = serializers.JSONField(required=False, default=list)
is_template = serializers.BooleanField(required=False, default=False)
status = serializers.CharField(required=False, default="active")
parent_template_id = serializers.UUIDField(
    source="parent_template.id", read_only=True, allow_null=True
)
```

New serializer:
```python
class ProcessDocumentEntrySerializer(serializers.ModelSerializer):
    entered_by_name = serializers.CharField(
        source="entered_by.get_display_name", read_only=True, allow_null=True
    )

    class Meta:
        model = ProcessDocumentEntry
        fields = [
            "id", "document", "entry_date", "entered_by", "entered_by_name",
            "data", "created_at",
        ]
        read_only_fields = ["id", "created_at", "entered_by_name"]
```

**Step 2: Regenerate `__init__.py` for serializers and fix imports**

```bash
python scripts/update_init.py
```

Update all files that import the old serializer names.

**Step 3: Verify**

```bash
python manage.py test apps.job --verbosity=2
```

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename and expand process document serializers

Add tags, is_template, status, parent_template fields.
Add ProcessDocumentEntrySerializer for structured form data."
```

---

### Task 5: Update views and add new endpoints

**Files:**
- Modify: `apps/job/views/safety_viewsets.py` (rename classes, add endpoints)
- Modify: `apps/job/urls_rest.py`

**Step 1: Update ViewSet**

In `safety_viewsets.py`:
- Rename `SafetyDocumentViewSet` → `ProcessDocumentViewSet`
- Rename `SafetyDocumentContentView` → `ProcessDocumentContentView`
- Update `get_queryset` to support `?type=`, `?tags=`, `?status=`, `?is_template=` filters
- Keep all existing JSA/SWP/SOP views working (they filter by tags now)

Add new action views:

```python
class ProcessDocumentFillView(APIView):
    """Create a new record from a template."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        from apps.job.services.process_document_service import ProcessDocumentService
        record = ProcessDocumentService().fill_template(
            template_id=pk,
            job_id=request.data.get("job_id"),
            filled_by=request.user.staff,
        )
        return Response(ProcessDocumentSerializer(record).data, status=status.HTTP_201_CREATED)


class ProcessDocumentCompleteView(APIView):
    """Mark a document as completed (read-only)."""
    permission_classes = [permissions.IsAuthenticated, IsOfficeStaff]

    def post(self, request, pk):
        from apps.job.services.process_document_service import ProcessDocumentService
        doc = ProcessDocumentService().complete_document(pk)
        return Response(ProcessDocumentSerializer(doc).data)
```

**Step 2: Update URL patterns**

In `apps/job/urls_rest.py`:
- Update router registration: `router.register(r"rest/process-documents", ProcessDocumentViewSet, ...)`
- Add new paths for `/fill/` and `/complete/`
- Keep existing JSA/SWP/SOP paths working

```python
# New endpoints
path("rest/process-documents/<uuid:pk>/content/", ProcessDocumentContentView.as_view(), ...),
path("rest/process-documents/<uuid:pk>/fill/", ProcessDocumentFillView.as_view(), ...),
path("rest/process-documents/<uuid:pk>/complete/", ProcessDocumentCompleteView.as_view(), ...),

# Existing endpoints preserved
path("rest/safety-documents/<uuid:pk>/content/", ProcessDocumentContentView.as_view(), ...),  # backward compat
```

**Step 3: Update JSA/SWP/SOP views for tag-based filtering**

Update `JSAListView`, `SWPListView`, `SOPListView` to filter by tags:
```python
# Was: SafetyDocument.objects.filter(job=job, document_type="jsa")
# Now:
ProcessDocument.objects.filter(job=job, tags__contains=["jsa"])
```

**Step 4: Verify**

```bash
python manage.py test apps.job --verbosity=2
```

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add process document endpoints with fill/complete workflow

New general-purpose endpoints at /rest/process-documents/ with
type/tag/status filtering. Template fill and complete actions.
Existing JSA/SWP/SOP endpoints preserved via tag filtering."
```

---

### Task 6: Update service layer

**Files:**
- Rename: `apps/job/services/safety_document_service.py` → `apps/job/services/process_document_service.py`
- Modify: `apps/job/services/google_docs_service.py`

**Step 1: Rename and update the service**

Rename `SafetyDocumentService` → `ProcessDocumentService`. Keep existing `generate_jsa`, `generate_swp`, `generate_sop` methods working (they now create `ProcessDocument` with appropriate tags).

Add new methods:

```python
@transaction.atomic
def fill_template(self, template_id, job_id=None, filled_by=None):
    """Create a new record from a template by copying the Google Doc."""
    template = ProcessDocument.objects.get(pk=template_id)
    if not template.is_template:
        raise ValueError("Document is not a template")

    # Copy Google Doc if it exists
    google_doc_id = ""
    google_doc_url = ""
    if template.google_doc_id:
        result = self.docs_service.copy_document(
            template.google_doc_id,
            title=f"{template.title} - {timezone.now().strftime('%Y-%m-%d')}",
        )
        google_doc_id = result.document_id
        google_doc_url = result.edit_url

    record = ProcessDocument.objects.create(
        document_type=template.document_type,
        tags=template.tags,
        title=template.title,
        document_number=template.document_number,
        company_name=template.company_name,
        site_location=template.site_location,
        google_doc_id=google_doc_id,
        google_doc_url=google_doc_url,
        is_template=False,
        status="draft",
        parent_template=template,
        job_id=job_id,
    )
    return record

@transaction.atomic
def complete_document(self, document_id):
    """Mark a document as completed and set Google Doc to read-only."""
    doc = ProcessDocument.objects.get(pk=document_id)
    doc.status = "completed"
    doc.save(update_fields=["status", "updated_at"])

    if doc.google_doc_id:
        self.docs_service.set_readonly(doc.google_doc_id)

    return doc
```

**Step 2: Add Google Docs helper methods**

In `apps/job/services/google_docs_service.py`, add:

```python
def copy_document(self, source_doc_id: str, title: str) -> GoogleDocResult:
    """Copy a Google Doc, returning the new document's ID and URL."""
    drive_service = _svc("drive", "v3")
    copied = drive_service.files().copy(
        fileId=source_doc_id,
        body={"name": title},
    ).execute()
    doc_id = copied["id"]
    edit_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    self._move_to_safety_folder(doc_id)
    _set_public_edit_permissions(doc_id)
    return GoogleDocResult(document_id=doc_id, edit_url=edit_url)

def set_readonly(self, document_id: str) -> None:
    """Remove edit permissions from a Google Doc."""
    drive_service = _svc("drive", "v3")
    permissions = drive_service.permissions().list(fileId=document_id).execute()
    for perm in permissions.get("permissions", []):
        if perm["role"] == "writer" and perm["id"] != "owner":
            drive_service.permissions().delete(
                fileId=document_id, permissionId=perm["id"]
            ).execute()
```

**Step 3: Verify**

```bash
python manage.py test apps.job --verbosity=2
```

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: add fill_template and complete_document to service layer

Copy Google Docs for template fill workflow. Set documents to
read-only on completion. Existing JSA/SWP/SOP generation preserved."
```

---

### Task 7: Create Dropbox import management command

**Files:**
- Create: `apps/job/management/commands/import_dropbox_hs_documents.py`

**Step 1: Create the command**

This command reads the Dropbox H&S folder and:
1. Uploads each `.doc`/`.docx` file to Google Drive (auto-converts to Google Docs format)
2. Creates a `ProcessDocument` record with metadata from the Doc.xxx numbering system

The command should:
- Accept `--dry-run` flag to preview without uploading
- Accept `--folder` argument for the Dropbox path
- Parse document numbers from filenames (e.g. "Doc.350 Gantry Crane..." → number="350")
- Map documents to types and tags based on the numbering system documented in the design doc
- Skip files that already have a `ProcessDocument` with that document_number
- Log each document processed

Key mapping logic:
```python
DOC_NUMBER_MAPPING = {
    # 100-series: policies and core docs
    ("100", "101"): ("procedure", ["safety", "policy"]),
    ("102", "103", "104", "105", "106"): ("reference", ["safety", "planning"]),
    ("107", "108", "110", "111", "113", "114", "119"): ("form", ["safety", "inspection"]),
    ("112",): ("register", ["safety", "ppe"]),
    ("115", "116"): ("form", ["safety", "hazard-id"]),
    ("117",): ("reference", ["safety", "maintenance"]),
    ("118",): ("procedure", ["safety", "lockout"]),
    ("120",): ("form", ["training", "induction"]),
    # 150-series: machine inspection
    # ... etc per design doc mapping table
    # 200-series: incident
    # 250-series: training
    # 300-series: hand tool SOPs
    # 350-series: machinery SOPs
    # 380: register
    # 400-series: emergency/general
    # 415-420: meeting forms
    # 450: machinery SOP
}
```

For uploading to Google Drive:
```python
from googleapiclient.http import MediaFileUpload

def upload_to_google_docs(self, file_path, title):
    """Upload a .doc/.docx file to Google Drive, converting to Google Docs format."""
    drive_service = _svc("drive", "v3")

    mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if file_path.endswith(".doc"):
        mime_type = "application/msword"

    media = MediaFileUpload(file_path, mimetype=mime_type)
    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",  # Convert to Google Docs
    }

    uploaded = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
    ).execute()

    doc_id = uploaded["id"]
    # Move to SafetyDocuments folder and set permissions
    # ... reuse existing GoogleDocsService methods

    return doc_id, f"https://docs.google.com/document/d/{doc_id}/edit"
```

Mark forms/templates with `is_template=True`:
- Doc numbers in: 107, 108, 110, 111, 113, 114, 115, 116, 119 (inspection forms)
- 151b, 153b, 168b (machine inspection checklists)
- 202, 205 (incident forms)
- 251, 252, 253, 255, 256, 257, 258, 259 (training forms)
- 400 (JSA template)
- 404 (evacuation drill record)
- 415, 416, 417 (meeting forms)

**Step 2: Test with dry-run**

```bash
python manage.py import_dropbox_hs_documents --folder="dropbox/Health & Safety" --dry-run
```

**Step 3: Run actual import**

```bash
python manage.py import_dropbox_hs_documents --folder="dropbox/Health & Safety"
```

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: add management command to import Dropbox H&S documents

Uploads .doc/.docx files to Google Drive, creates ProcessDocument
records with document numbers, types, and tags from the MSM
numbering system."
```

---

### Task 8: Write frontend spec

**Files:**
- Create: `docs/plans/2026-03-03-process-documents-frontend-spec.md`

This is a standalone spec document for the frontend Claude to implement from. See the companion file for full details.

**Step 1: Write the spec (see next section)**

**Step 2: Commit**

```bash
git add docs/plans/2026-03-03-process-documents-frontend-spec.md
git commit -m "docs: add frontend spec for process documents UI"
```

---

### Task 9: Tests

**Files:**
- Create: `apps/job/tests/test_process_document.py`
- Create: `apps/job/tests/test_process_document_service.py`

**Step 1: Model tests**

```python
import pytest
from apps.job.models import ProcessDocument

@pytest.mark.django_db
class TestProcessDocument:
    def test_create_procedure_with_tags(self):
        doc = ProcessDocument.objects.create(
            document_type="procedure",
            title="Drill Press SOP",
            document_number="355",
            tags=["safety", "sop", "machinery"],
            company_name="Morris Sheetmetal",
        )
        assert doc.document_type == "procedure"
        assert "sop" in doc.tags
        assert doc.status == "active"
        assert doc.is_template is False

    def test_create_template_form(self):
        template = ProcessDocument.objects.create(
            document_type="form",
            title="Ladder Inspection Checklist",
            document_number="110",
            tags=["safety", "inspection"],
            is_template=True,
            company_name="Morris Sheetmetal",
        )
        assert template.is_template is True

    def test_completed_record_links_to_template(self):
        template = ProcessDocument.objects.create(
            document_type="form",
            title="Ladder Inspection",
            document_number="110",
            is_template=True,
            company_name="Morris Sheetmetal",
        )
        record = ProcessDocument.objects.create(
            document_type="form",
            title="Ladder Inspection",
            status="completed",
            parent_template=template,
            company_name="Morris Sheetmetal",
        )
        assert record.parent_template == template
        assert template.completed_records.count() == 1

    def test_filter_by_tags_contains(self):
        ProcessDocument.objects.create(
            document_type="procedure",
            title="SWP1",
            tags=["safety", "swp"],
            company_name="Test",
        )
        ProcessDocument.objects.create(
            document_type="procedure",
            title="SOP1",
            tags=["sop"],
            company_name="Test",
        )
        swps = ProcessDocument.objects.filter(tags__contains=["swp"])
        assert swps.count() == 1
        assert swps.first().title == "SWP1"
```

**Step 2: Service tests (mocking Google Docs)**

```python
from unittest.mock import MagicMock, patch

@pytest.mark.django_db
class TestProcessDocumentService:
    @patch("apps.job.services.process_document_service.GoogleDocsService")
    def test_fill_template_copies_google_doc(self, MockDocsService):
        mock_docs = MockDocsService.return_value
        mock_docs.copy_document.return_value = GoogleDocResult(
            document_id="new-doc-id",
            edit_url="https://docs.google.com/document/d/new-doc-id/edit",
        )

        template = ProcessDocument.objects.create(
            document_type="form",
            title="Inspection",
            is_template=True,
            google_doc_id="template-doc-id",
            company_name="Test",
        )

        service = ProcessDocumentService()
        service.docs_service = mock_docs
        record = service.fill_template(template_id=template.pk)

        mock_docs.copy_document.assert_called_once()
        assert record.parent_template == template
        assert record.status == "draft"
        assert record.google_doc_id == "new-doc-id"

    def test_fill_non_template_raises(self):
        doc = ProcessDocument.objects.create(
            document_type="procedure",
            title="Not a template",
            is_template=False,
            company_name="Test",
        )
        service = ProcessDocumentService()
        with pytest.raises(ValueError, match="not a template"):
            service.fill_template(template_id=doc.pk)
```

**Step 3: Run tests**

```bash
pytest apps/job/tests/test_process_document.py -v
pytest apps/job/tests/test_process_document_service.py -v
```

**Step 4: Commit**

```bash
git add -A
git commit -m "test: add process document model and service tests"
```
