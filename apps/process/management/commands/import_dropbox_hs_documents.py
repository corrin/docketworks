"""Import Dropbox Health & Safety documents into Procedure/Form records.

Walks a folder tree finding .doc/.docx files with the Doc.NNN naming
convention and creates Procedure or Form records with type, tags, and
metadata implied by the mapping below. One-per-client import, not a sync:
documents already present (by document number) are skipped, never updated.

Two import paths based on DOC_MAPPING:
- Prose docs (procedure/reference): uploaded to Google Drive as Google Docs,
  stored as Procedure.
- Form/register definitions: Django-only Form records, no Google Doc.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from django.core.management.base import BaseCommand, CommandError, CommandParser
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

if TYPE_CHECKING:
    from googleapiclient._apis.drive.v3.schemas import File

from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.process.models import Form, Procedure

# Maps individual doc numbers to (document_type, category, tags). Which model
# a row lands in follows from the type: form/register -> Form, otherwise
# Procedure. category is derived by hand from each row's type+tags via the
# rules in apps/process/migrations/_0003_helpers.py — asserted to agree in
# TestDocMappingCategoriesMatchTheRule (never re-derive at import time, so
# the mapping and the backfill migration cannot silently diverge).
DOC_MAPPING: dict[str, tuple[str, str, list[str]]] = {
    # Policies (procedures with policy tag)
    "100": ("procedure", "safety", ["safety", "policy"]),
    "101": ("procedure", "safety", ["safety", "policy"]),
    # Planning/reference docs
    "102": ("reference", "reference", ["safety", "planning"]),
    "103": ("reference", "reference", ["safety", "planning"]),
    "105": ("reference", "reference", ["safety", "planning"]),
    "106": ("reference", "reference", ["safety", "planning"]),
    # Inspection forms (templates)
    "107": ("procedure", "safety", ["safety", "inspection"]),
    "108": ("form", "safety", ["safety", "inspection"]),
    "110": ("form", "safety", ["safety", "inspection"]),
    "111": ("form", "safety", ["safety", "inspection"]),
    "112": ("form", "safety", ["safety", "ppe"]),
    "113": ("form", "safety", ["safety", "inspection"]),
    "114": ("form", "safety", ["safety", "inspection"]),
    "115": ("form", "safety", ["safety", "hazard-id"]),
    "116": ("form", "safety", ["safety", "hazard-id"]),
    "117": ("form", "safety", ["safety", "maintenance"]),
    "118": ("procedure", "safety", ["safety", "lockout"]),
    "119": ("form", "safety", ["safety", "inspection"]),
    "120": ("reference", "reference", ["training", "induction"]),
    # Machine inspection (150-series) — a=procedure, b=checklist form
    "151a": ("procedure", "safety", ["safety", "inspection", "machinery"]),
    "151b": ("form", "safety", ["safety", "inspection", "machinery"]),
    "153a": ("procedure", "safety", ["safety", "inspection", "machinery"]),
    "153b": ("form", "safety", ["safety", "inspection", "machinery"]),
    "168a": ("procedure", "safety", ["safety", "inspection", "machinery"]),
    "168b": ("form", "safety", ["safety", "inspection", "machinery"]),
    "172": ("procedure", "safety", ["safety", "inspection", "machinery"]),
    # Incident management (200-series)
    "202": ("form", "incident", ["safety", "incident"]),
    "203": ("procedure", "safety", ["safety", "incident"]),
    "204": ("procedure", "safety", ["safety", "incident"]),
    "205": ("form", "incident", ["safety", "incident"]),
    "206": ("reference", "reference", ["safety", "incident"]),
    # Training docs, 250 series
    "250": ("reference", "reference", ["training"]),
    "251": ("procedure", "training", ["training", "induction"]),
    "252": ("form", "training", ["training", "refresher"]),
    "253": ("form", "training", ["training", "induction"]),
    "255": ("form", "training", ["training", "induction"]),
    "256": ("form", "training", ["training", "refresher", "machinery"]),
    "257": ("form", "training", ["training", "refresher", "handtool"]),
    "258": ("form", "training", ["training", "refresher", "lockout"]),
    "259": ("form", "training", ["training", "induction"]),
    # Hand tool SOPs (300-series)
    "300": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "301": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "302": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "303": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "304": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "305": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "306": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "307": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "308": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "309": ("procedure", "safety", ["safety", "sop", "handtool"]),
    "310": ("procedure", "safety", ["safety", "sop", "handtool"]),
    # Machinery SOPs (350-series)
    "350": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "351": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "352": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "353": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "354": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "355": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "357": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "359": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "360": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "361": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "362": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "363": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "364": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "366": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "369": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "370": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "372": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "373": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "374": ("procedure", "safety", ["safety", "sop", "machinery"]),
    "375": ("procedure", "safety", ["safety", "sop", "machinery"]),
    # Registers
    "380": ("register", "register", ["safety", "hazard"]),
    # Emergency and general docs, 400 series
    "401": ("procedure", "safety", ["safety", "emergency"]),
    "402": ("reference", "reference", ["safety", "sop"]),
    "403": ("register", "register", ["safety", "chemical"]),
    "404": ("form", "safety", ["safety", "emergency"]),
    "405": ("reference", "reference", ["safety", "emergency"]),
    # Meeting forms (415-420)
    "415": ("form", "meeting", ["administration", "meeting"]),
    "416": ("form", "meeting", ["administration", "meeting"]),
    "417": ("form", "meeting", ["administration", "meeting"]),
    # Air compressor
    "450": ("procedure", "safety", ["safety", "sop", "machinery"]),
}


class FormSchema(TypedDict):
    """Entry-field schema stored on a Form template."""

    fields: list[dict[str, object]]


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_MONTHLY_MACHINE_CHECKLIST: FormSchema = {
    "fields": [
        {"key": "month", "label": "Month", "type": "select", "options": _MONTHS},
        {"key": "inspected", "label": "Inspected", "type": "boolean"},
        {"key": "inspector", "label": "Inspector", "type": "text"},
        {"key": "notes", "label": "Notes", "type": "textarea"},
    ]
}

# Form schemas for template documents. Each defines the fields for ONE
# FormEntry row. Field types: text, textarea, date, boolean, number, select.
FORM_SCHEMAS: dict[str, FormSchema] = {
    # Inspection/Maintenance
    "108": {
        "fields": [
            {"key": "equipment_name", "label": "Equipment Name", "type": "text", "required": True},
            {"key": "fault_description", "label": "Fault Description", "type": "textarea"},
            {"key": "repair_action", "label": "Repair Action", "type": "textarea"},
            {"key": "repair_date", "label": "Repair Date", "type": "date"},
            {"key": "signed_off_by", "label": "Signed Off By", "type": "text"},
        ]
    },
    "110": {
        "fields": [
            {"key": "ladder_id", "label": "Ladder ID", "type": "text", "required": True},
            {
                "key": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["OK", "Needs Repair", "Out of Service"],
            },
            {"key": "notes", "label": "Notes", "type": "textarea"},
            {"key": "inspector", "label": "Inspector", "type": "text"},
        ]
    },
    "111": {
        "fields": [
            {"key": "machine_name", "label": "Machine Name", "type": "text", "required": True},
            {"key": "checked", "label": "Checked", "type": "boolean"},
            {"key": "notes", "label": "Notes", "type": "textarea"},
            {"key": "inspector", "label": "Inspector", "type": "text"},
        ]
    },
    "119": {
        "fields": [
            {"key": "area", "label": "Area", "type": "text", "required": True},
            {"key": "item", "label": "Item", "type": "text", "required": True},
            {
                "key": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["OK", "Needs Attention", "Urgent"],
            },
            {"key": "action_required", "label": "Action Required", "type": "textarea"},
            {"key": "inspector", "label": "Inspector", "type": "text"},
        ]
    },
    # Machine inspection checklists (monthly grid)
    "151b": _MONTHLY_MACHINE_CHECKLIST,
    "153b": _MONTHLY_MACHINE_CHECKLIST,
    "168b": _MONTHLY_MACHINE_CHECKLIST,
    # Registers
    "112": {
        "fields": [
            {"key": "staff_name", "label": "Staff Name", "type": "text", "required": True},
            {"key": "item_issued", "label": "Item Issued", "type": "text", "required": True},
            {"key": "quantity", "label": "Quantity", "type": "number"},
            {"key": "date_issued", "label": "Date Issued", "type": "date"},
            {"key": "acknowledged", "label": "Acknowledged", "type": "boolean"},
        ]
    },
    "117": {
        "fields": [
            {
                "key": "contractor_name",
                "label": "Contractor Name",
                "type": "text",
                "required": True,
            },
            {"key": "trade", "label": "Trade", "type": "text"},
            {"key": "contact_phone", "label": "Contact Phone", "type": "text"},
            {"key": "insurance_expiry", "label": "Insurance Expiry", "type": "date"},
            {"key": "approved_by", "label": "Approved By", "type": "text"},
        ]
    },
    # First aid inventories
    "113": {
        "fields": [
            {"key": "truck_number", "label": "Truck Number", "type": "text", "required": True},
            {"key": "item", "label": "Item", "type": "text", "required": True},
            {"key": "quantity", "label": "Quantity", "type": "number"},
            {
                "key": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["OK", "Low", "Replace"],
            },
            {"key": "checked_by", "label": "Checked By", "type": "text"},
        ]
    },
    "114": {
        "fields": [
            {"key": "item", "label": "Item", "type": "text", "required": True},
            {"key": "quantity", "label": "Quantity", "type": "number"},
            {
                "key": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["OK", "Low", "Replace"],
            },
            {"key": "checked_by", "label": "Checked By", "type": "text"},
        ]
    },
    # Hazard ID
    "115": {
        "fields": [
            {"key": "task", "label": "Task", "type": "text", "required": True},
            {"key": "hazards", "label": "Hazards", "type": "textarea"},
            {
                "key": "risk_level",
                "label": "Risk Level",
                "type": "select",
                "options": ["Low", "Medium", "High", "Extreme"],
            },
            {"key": "controls", "label": "Controls", "type": "textarea"},
            {"key": "responsible_person", "label": "Responsible Person", "type": "text"},
        ]
    },
    "116": {
        "fields": [
            {"key": "hazard", "label": "Hazard", "type": "text", "required": True},
            {
                "key": "risk_level",
                "label": "Risk Level",
                "type": "select",
                "options": ["Low", "Medium", "High", "Extreme"],
            },
            {"key": "control_measure", "label": "Control Measure", "type": "textarea"},
            {"key": "proceed", "label": "Proceed", "type": "boolean"},
        ]
    },
    # Incident
    "202": {
        "fields": [
            {
                "key": "date_of_incident",
                "label": "Date of Incident",
                "type": "date",
                "required": True,
            },
            {"key": "location", "label": "Location", "type": "text"},
            {"key": "description", "label": "Description", "type": "textarea"},
            {"key": "persons_involved", "label": "Persons Involved", "type": "textarea"},
            {"key": "immediate_cause", "label": "Immediate Cause", "type": "textarea"},
            {"key": "root_cause", "label": "Root Cause", "type": "textarea"},
            {"key": "corrective_actions", "label": "Corrective Actions", "type": "textarea"},
            {"key": "completed_by", "label": "Completed By", "type": "text"},
            {"key": "review_date", "label": "Review Date", "type": "date"},
        ]
    },
    "205": {
        "fields": [
            {"key": "employee_name", "label": "Employee Name", "type": "text", "required": True},
            {"key": "injury_description", "label": "Injury Description", "type": "textarea"},
            {"key": "week_number", "label": "Week Number", "type": "number"},
            {"key": "duties", "label": "Duties", "type": "textarea"},
            {"key": "restrictions", "label": "Restrictions", "type": "textarea"},
            {"key": "review_date", "label": "Review Date", "type": "date"},
            {"key": "supervisor", "label": "Supervisor", "type": "text"},
        ]
    },
    # Training sign-offs
    "252": {
        "fields": [
            {"key": "staff_name", "label": "Staff Name", "type": "text", "required": True},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "trainer", "label": "Trainer", "type": "text"},
            {"key": "signature_confirmed", "label": "Signature Confirmed", "type": "boolean"},
        ]
    },
    "253": {
        "fields": [
            {"key": "item", "label": "Item", "type": "text", "required": True},
            {"key": "completed", "label": "Completed", "type": "boolean"},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "inductee_initials", "label": "Inductee Initials", "type": "text"},
            {"key": "trainer_initials", "label": "Trainer Initials", "type": "text"},
        ]
    },
    "255": {
        "fields": [
            {"key": "staff_name", "label": "Staff Name", "type": "text", "required": True},
            {"key": "sop_number", "label": "SOP Number", "type": "text"},
            {"key": "sop_title", "label": "SOP Title", "type": "text"},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "signature_confirmed", "label": "Signature Confirmed", "type": "boolean"},
        ]
    },
    "256": {
        "fields": [
            {"key": "staff_name", "label": "Staff Name", "type": "text", "required": True},
            {"key": "sop_number", "label": "SOP Number", "type": "text"},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "trainer", "label": "Trainer", "type": "text"},
            {"key": "signature_confirmed", "label": "Signature Confirmed", "type": "boolean"},
        ]
    },
    "257": {
        "fields": [
            {"key": "staff_name", "label": "Staff Name", "type": "text", "required": True},
            {"key": "sop_number", "label": "SOP Number", "type": "text"},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "trainer", "label": "Trainer", "type": "text"},
            {"key": "signature_confirmed", "label": "Signature Confirmed", "type": "boolean"},
        ]
    },
    "258": {
        "fields": [
            {"key": "staff_name", "label": "Staff Name", "type": "text", "required": True},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "trainer", "label": "Trainer", "type": "text"},
            {"key": "signature_confirmed", "label": "Signature Confirmed", "type": "boolean"},
        ]
    },
    "259": {
        "fields": [
            {"key": "item", "label": "Item", "type": "text", "required": True},
            {"key": "date_issued", "label": "Date Issued", "type": "date"},
            {"key": "condition", "label": "Condition", "type": "text"},
            {"key": "acknowledged", "label": "Acknowledged", "type": "boolean"},
        ]
    },
    # Meetings
    "415": {
        "fields": [
            {"key": "agenda_item", "label": "Agenda Item", "type": "text", "required": True},
            {"key": "discussion", "label": "Discussion", "type": "textarea"},
            {"key": "action", "label": "Action", "type": "textarea"},
            {"key": "responsible_person", "label": "Responsible Person", "type": "text"},
            {"key": "due_date", "label": "Due Date", "type": "date"},
        ]
    },
    "416": {
        "fields": [
            {"key": "agenda_item", "label": "Agenda Item", "type": "text", "required": True},
            {"key": "presenter", "label": "Presenter", "type": "text"},
            {"key": "notes", "label": "Notes", "type": "textarea"},
        ]
    },
    "417": {
        "fields": [
            {"key": "staff_name", "label": "Staff Name", "type": "text", "required": True},
            {"key": "present", "label": "Present", "type": "boolean"},
            {"key": "signature_confirmed", "label": "Signature Confirmed", "type": "boolean"},
        ]
    },
    # Emergency
    "404": {
        "fields": [
            {"key": "time_started", "label": "Time Started", "type": "text", "required": True},
            {"key": "time_completed", "label": "Time Completed", "type": "text"},
            {"key": "assembly_point", "label": "Assembly Point", "type": "text"},
            {"key": "all_accounted", "label": "All Accounted For", "type": "boolean"},
            {"key": "issues", "label": "Issues", "type": "textarea"},
            {"key": "conducted_by", "label": "Conducted By", "type": "text"},
        ]
    },
}

# Extracts the doc number from filenames like "Doc.350", "Doc 350", "Doc.350a"
DOC_NUMBER_RE = re.compile(r"Doc\.?\s*(\d+[ab]?)", re.IGNORECASE)

# Folder names to skip entirely (source-tree conventions in the client's Dropbox)
SKIP_FOLDERS = {"zMSM Old Docs", "zPauls Folder", "Archive"}

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]


def _should_skip_folder(folder_name: str) -> bool:
    """Return True if this folder is excluded from scanning."""
    return folder_name in SKIP_FOLDERS or folder_name.startswith("z")


def _extract_doc_info(filename: str) -> tuple[str, str] | None:
    """Extract (doc_number, title) from a filename, or None if no Doc.NNN match."""
    match = DOC_NUMBER_RE.search(filename)
    if not match:
        return None

    doc_number = match.group(1)
    stem = Path(filename).stem
    title_start = match.end()
    title = stem[title_start:].strip().lstrip(".-_ ") if title_start <= len(stem) else stem
    if not title:
        title = f"Document {doc_number}"
    return doc_number, title


class Command(BaseCommand):
    """One-per-client bulk import of the Dropbox H&S document tree."""

    help = "Import Dropbox Health & Safety documents into Procedure/Form records"

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the source folder, dry-run flag, and Google credentials path."""
        parser.add_argument(
            "--folder",
            required=True,
            help="Path to the H&S folder (e.g. 'dropbox/Health & Safety')",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview without uploading or creating records",
        )
        parser.add_argument(
            "--credentials",
            help=(
                "Path to a Google service account JSON key file with domain-wide "
                "delegation. Required unless --dry-run: prose documents are "
                "uploaded to Google Drive."
            ),
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Run the import, persisting any unexpected failure with its context."""
        try:
            self._handle(**options)
        except Exception as exc:
            persist_app_error(exc)
            raise

    def _handle(self, **options: object) -> None:
        folder = options["folder"]
        dry_run = options["dry_run"]
        credentials = options["credentials"]
        if not isinstance(folder, str):
            raise TypeError("The folder option must be a string")
        if not isinstance(dry_run, bool):
            raise TypeError("The dry-run option must be a boolean")
        if credentials is not None and not isinstance(credentials, str):
            raise TypeError("The credentials option must be a string")

        folder_path = Path(folder)
        if not folder_path.exists():
            raise CommandError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise CommandError(f"Path is not a directory: {folder_path}")

        reference_folder_id = self._validate_configuration(dry_run=dry_run, credentials=credentials)

        resolved = self._resolve_duplicates(self._discover_files(folder_path))
        imported, skipped_existing, skipped_no_mapping = self._import_documents(
            resolved, dry_run=dry_run, reference_folder_id=reference_folder_id
        )

        self.stdout.write("")
        action = "Would import" if dry_run else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {imported} documents, "
                f"skipped {skipped_existing} (already exist), "
                f"skipped {skipped_no_mapping} (no mapping)"
            )
        )

    def _validate_configuration(self, *, dry_run: bool, credentials: str | None) -> str | None:
        """Check upload prerequisites upfront and return the Drive folder id.

        Dry runs create and upload nothing, so they may proceed unconfigured.
        """
        company = CompanyDefaults.get_solo()
        reference_folder_id = company.gdrive_reference_library_folder_id
        if not dry_run:
            # v1 could fall back to ambient application credentials; v2 has no
            # Google client elsewhere yet, so the key file is the only path.
            if not credentials:
                raise CommandError(
                    "--credentials is required for a real import: prose documents "
                    "are uploaded to Google Drive. Use --dry-run to preview without it."
                )
            if not reference_folder_id:
                raise CommandError(
                    "CompanyDefaults.gdrive_reference_library_folder_id is not configured. "
                    "Set it in Settings before uploading."
                )
            if not company.company_email:
                raise CommandError(
                    "CompanyDefaults.company_email is not set. "
                    "Google Workspace domain-wide delegation needs a user to impersonate — "
                    "populate CompanyDefaults.company_email in Settings."
                )
        self._credentials_file = credentials
        self._impersonate_email = company.company_email
        return reference_folder_id

    def _import_documents(
        self,
        resolved: dict[str, tuple[Path, str]],
        *,
        dry_run: bool,
        reference_folder_id: str | None,
    ) -> tuple[int, int, int]:
        """Import each resolved document; return (imported, existing, unmapped) counts."""
        resolved_keys = list(resolved.keys())
        existing_numbers = set(
            Procedure.objects.filter(document_number__in=resolved_keys).values_list(
                "document_number", flat=True
            )
        ) | set(
            Form.objects.filter(document_number__in=resolved_keys).values_list(
                "document_number", flat=True
            )
        )

        imported = 0
        skipped_existing = 0
        skipped_no_mapping = 0

        for doc_number in sorted(resolved.keys(), key=lambda x: x.zfill(5)):
            file_path, title = resolved[doc_number]

            if doc_number in existing_numbers:
                skipped_existing += 1
                self.stdout.write(f'  Skipped Doc.{doc_number} "{title}" (already exists)')
                continue

            if doc_number not in DOC_MAPPING:
                skipped_no_mapping += 1
                self.stdout.write(
                    self.style.WARNING(f'  Skipped Doc.{doc_number} "{title}" (no mapping)')
                )
                continue

            doc_type, category, tags = DOC_MAPPING[doc_number]
            path_label = "[FORM]" if doc_type in ("form", "register") else "[GDOC]"

            if dry_run:
                self.stdout.write(
                    f'[DRY RUN] {path_label} Doc.{doc_number} "{title}" -> {doc_type} {tags}'
                )
                imported += 1
                continue

            if doc_type in ("form", "register"):
                self._import_form(
                    doc_number, title, doc_type, category, tags, file_path, path_label
                )
            else:
                if reference_folder_id is None:
                    raise CommandError(
                        "gdrive_reference_library_folder_id became unset mid-run; aborting."
                    )
                self._import_procedure(
                    doc_number,
                    title,
                    doc_type,
                    category,
                    tags,
                    file_path,
                    path_label,
                    reference_folder_id,
                )
            imported += 1

        return imported, skipped_existing, skipped_no_mapping

    def _import_form(  # noqa: PLR0913, PLR0917 -- one row's identity is genuinely seven values
        self,
        doc_number: str,
        title: str,
        doc_type: str,
        category: str,
        tags: list[str],
        file_path: Path,
        path_label: str,
    ) -> None:
        """Create a Django-only Form/register record (no Google Doc)."""
        schema: FormSchema | dict[str, object] = FORM_SCHEMAS.get(doc_number, {})
        doc = Form.objects.create(
            document_type=doc_type,
            category=category,
            tags=tags,
            status="active",
            document_number=doc_number,
            title=title,
            form_schema=schema,
        )
        # Backdate created_at to the original file creation date; a queryset
        # update because auto_now_add ignores a value passed to create().
        Form.objects.filter(pk=doc.pk).update(created_at=self._file_mtime(file_path))
        self.stdout.write(
            self.style.SUCCESS(
                f'{path_label} Imported Doc.{doc_number} "{title}" -> {doc_type} {tags}'
            )
        )

    def _import_procedure(  # noqa: PLR0913, PLR0917 -- one row's identity is genuinely eight values
        self,
        doc_number: str,
        title: str,
        doc_type: str,
        category: str,
        tags: list[str],
        file_path: Path,
        path_label: str,
        folder_id: str,
    ) -> None:
        """Upload a prose doc to Google Drive and create its Procedure record."""
        google_doc_id, google_doc_url = self._upload_to_google_docs(
            file_path, f"Doc.{doc_number} {title}", folder_id
        )
        doc = Procedure.objects.create(
            document_type=doc_type,
            category=category,
            tags=tags,
            status="active",
            document_number=doc_number,
            title=title,
            site_location=None,
            google_doc_id=google_doc_id,
            google_doc_url=google_doc_url,
        )
        Procedure.objects.filter(pk=doc.pk).update(created_at=self._file_mtime(file_path))
        self.stdout.write(
            self.style.SUCCESS(
                f'{path_label} Imported Doc.{doc_number} "{title}" '
                f"-> {doc_type} {tags} ({google_doc_url})"
            )
        )

    @staticmethod
    def _file_mtime(file_path: Path) -> datetime:
        """Return the file's last-modified time as an aware UTC datetime.

        Not ``st_ctime``, which v1 used and called a creation time: on Linux
        that is the inode's metadata-change time, so a Dropbox sync, a copy or
        a restore rewrites it to the moment the tree landed on this machine —
        making every imported document look created on import day. ``st_mtime``
        is what Dropbox preserves, and is the closest honest answer to "when
        was this document written".
        """
        return datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)

    def _discover_files(self, folder_path: Path) -> dict[str, list[tuple[Path, str]]]:
        """Walk the tree finding .doc/.docx files with the Doc.NNN pattern.

        Returns a dict mapping doc_number -> list of (file_path, title).
        """
        candidates: dict[str, list[tuple[Path, str]]] = {}

        for file_path in folder_path.rglob("*"):
            if not file_path.is_file():
                continue
            # .lnk files are Windows shortcuts; anything else non-doc is noise.
            if file_path.suffix.lower() not in (".doc", ".docx"):
                continue
            if self._is_in_skip_folder(file_path, folder_path):
                continue

            doc_info = _extract_doc_info(file_path.name)
            if doc_info is None:
                continue
            doc_number, title = doc_info
            candidates.setdefault(doc_number, []).append((file_path, title))

        return candidates

    def _is_in_skip_folder(self, file_path: Path, root: Path) -> bool:
        """Whether the file sits inside a folder excluded from scanning."""
        relative = file_path.relative_to(root)
        # Parent folder names only, not the file's own name.
        return any(_should_skip_folder(part) for part in relative.parts[:-1])

    def _resolve_duplicates(
        self, candidates: dict[str, list[tuple[Path, str]]]
    ) -> dict[str, tuple[Path, str]]:
        """Pick one file per doc number: prefer .doc over .docx, then latest mtime."""
        resolved: dict[str, tuple[Path, str]] = {}

        for doc_number, file_list in candidates.items():
            if len(file_list) == 1:
                resolved[doc_number] = file_list[0]
                continue

            doc_files = [f for f in file_list if f[0].suffix.lower() == ".doc"]
            docx_files = [f for f in file_list if f[0].suffix.lower() == ".docx"]
            if doc_files:
                best = max(doc_files, key=lambda f: f[0].stat().st_mtime)
            elif docx_files:
                best = max(docx_files, key=lambda f: f[0].stat().st_mtime)
            else:
                best = file_list[0]
            resolved[doc_number] = best

        return resolved

    def _upload_to_google_docs(
        self, file_path: Path, title: str, folder_id: str
    ) -> tuple[str, str]:
        """Upload a .doc/.docx to Drive converting to Google Docs; return (id, url)."""
        if not self._credentials_file:
            raise CommandError("Google credentials are required to upload prose documents.")
        if not self._impersonate_email:
            raise CommandError(
                "CompanyDefaults.company_email is not set; there is no Workspace "
                "user to impersonate for the upload."
            )
        creds = service_account.Credentials.from_service_account_file(
            self._credentials_file, scopes=GOOGLE_SCOPES
        ).with_subject(self._impersonate_email)
        drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)

        ext = file_path.suffix.lower()
        mime_types = {
            ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ".doc": "application/msword",
        }
        mime_type = mime_types.get(ext, "application/octet-stream")

        # Preserve the modification time Dropbox carries. No createdTime is
        # sent: v1 sent st_ctime, which is the local inode-change time rather
        # than a creation date, so it asserted something false. Letting Drive
        # stamp the real upload time is the truthful alternative.
        modified_time = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC).isoformat()

        media = MediaFileUpload(str(file_path), mimetype=mime_type)
        file_metadata: File = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id],
            "modifiedTime": modified_time,
        }

        uploaded = (
            drive_service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )

        doc_id = uploaded["id"]

        # Google ignores modifiedTime during conversion uploads,
        # so set it with a separate update call
        drive_service.files().update(
            fileId=doc_id,
            body={"modifiedTime": modified_time},
            supportsAllDrives=True,
        ).execute()

        edit_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return doc_id, edit_url
