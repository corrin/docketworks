"""
Management command to import Dropbox Health & Safety documents into Procedure/Form records.

Walks a folder structure finding .doc and .docx files with Doc.NNN naming convention
and creates Procedure or Form records with appropriate type, tags, and metadata.

Two import paths based on DOC_MAPPING:
- Prose docs: uploaded to Google Drive, stored as Procedure
- Form/register definitions: Django-only Form records, no Google Doc
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.process.models import Form, Procedure
from apps.workflow.models import CompanyDefaults

# Maps individual doc numbers to (document_type, tags, is_form_or_register)
DOC_MAPPING = {
    # Policies (procedures with policy tag)
    "100": ("procedure", ["safety", "policy"], False),
    "101": ("procedure", ["safety", "policy"], False),
    # Planning/reference docs
    "102": ("reference", ["safety", "planning"], False),
    "103": ("reference", ["safety", "planning"], False),
    "105": ("reference", ["safety", "planning"], False),
    "106": ("reference", ["safety", "planning"], False),
    # Inspection forms (templates)
    "107": ("procedure", ["safety", "inspection"], False),
    "108": ("form", ["safety", "inspection"], True),
    "110": ("form", ["safety", "inspection"], True),
    "111": ("form", ["safety", "inspection"], True),
    "112": ("form", ["safety", "ppe"], True),
    "113": ("form", ["safety", "inspection"], True),
    "114": ("form", ["safety", "inspection"], True),
    "115": ("form", ["safety", "hazard-id"], True),
    "116": ("form", ["safety", "hazard-id"], True),
    "117": ("form", ["safety", "maintenance"], True),
    "118": ("procedure", ["safety", "lockout"], False),
    "119": ("form", ["safety", "inspection"], True),
    "120": ("reference", ["training", "induction"], False),
    # Machine inspection (150-series) — a=procedure, b=checklist form
    "151a": ("procedure", ["safety", "inspection", "machinery"], False),
    "151b": ("form", ["safety", "inspection", "machinery"], True),
    "153a": ("procedure", ["safety", "inspection", "machinery"], False),
    "153b": ("form", ["safety", "inspection", "machinery"], True),
    "168a": ("procedure", ["safety", "inspection", "machinery"], False),
    "168b": ("form", ["safety", "inspection", "machinery"], True),
    "172": ("procedure", ["safety", "inspection", "machinery"], False),
    # Incident management (200-series)
    "202": ("form", ["safety", "incident"], True),
    "203": ("procedure", ["safety", "incident"], False),
    "204": ("procedure", ["safety", "incident"], False),
    "205": ("form", ["safety", "incident"], True),
    "206": ("reference", ["safety", "incident"], False),
    # Training (250-series)
    "250": ("reference", ["training"], False),
    "251": ("procedure", ["training", "induction"], False),
    "252": ("form", ["training", "refresher"], True),
    "253": ("form", ["training", "induction"], True),
    "255": ("form", ["training", "induction"], True),
    "256": ("form", ["training", "refresher", "machinery"], True),
    "257": ("form", ["training", "refresher", "handtool"], True),
    "258": ("form", ["training", "refresher", "lockout"], True),
    "259": ("form", ["training", "induction"], True),
    # Hand tool SOPs (300-series)
    "300": ("procedure", ["safety", "sop", "handtool"], False),
    "301": ("procedure", ["safety", "sop", "handtool"], False),
    "302": ("procedure", ["safety", "sop", "handtool"], False),
    "303": ("procedure", ["safety", "sop", "handtool"], False),
    "304": ("procedure", ["safety", "sop", "handtool"], False),
    "305": ("procedure", ["safety", "sop", "handtool"], False),
    "306": ("procedure", ["safety", "sop", "handtool"], False),
    "307": ("procedure", ["safety", "sop", "handtool"], False),
    "308": ("procedure", ["safety", "sop", "handtool"], False),
    "309": ("procedure", ["safety", "sop", "handtool"], False),
    "310": ("procedure", ["safety", "sop", "handtool"], False),
    # Machinery SOPs (350-series)
    "350": ("procedure", ["safety", "sop", "machinery"], False),
    "351": ("procedure", ["safety", "sop", "machinery"], False),
    "352": ("procedure", ["safety", "sop", "machinery"], False),
    "353": ("procedure", ["safety", "sop", "machinery"], False),
    "354": ("procedure", ["safety", "sop", "machinery"], False),
    "355": ("procedure", ["safety", "sop", "machinery"], False),
    "357": ("procedure", ["safety", "sop", "machinery"], False),
    "359": ("procedure", ["safety", "sop", "machinery"], False),
    "360": ("procedure", ["safety", "sop", "machinery"], False),
    "361": ("procedure", ["safety", "sop", "machinery"], False),
    "362": ("procedure", ["safety", "sop", "machinery"], False),
    "363": ("procedure", ["safety", "sop", "machinery"], False),
    "364": ("procedure", ["safety", "sop", "machinery"], False),
    "366": ("procedure", ["safety", "sop", "machinery"], False),
    "369": ("procedure", ["safety", "sop", "machinery"], False),
    "370": ("procedure", ["safety", "sop", "machinery"], False),
    "372": ("procedure", ["safety", "sop", "machinery"], False),
    "373": ("procedure", ["safety", "sop", "machinery"], False),
    "374": ("procedure", ["safety", "sop", "machinery"], False),
    "375": ("procedure", ["safety", "sop", "machinery"], False),
    # Registers
    "380": ("register", ["safety", "hazard"], False),
    # Emergency/general (400-series)
    "401": ("procedure", ["safety", "emergency"], False),
    "402": ("reference", ["safety", "sop"], False),
    "403": ("register", ["safety", "chemical"], False),
    "404": ("form", ["safety", "emergency"], True),
    "405": ("reference", ["safety", "emergency"], False),
    # Meeting forms (415-420)
    "415": ("form", ["administration", "meeting"], True),
    "416": ("form", ["administration", "meeting"], True),
    "417": ("form", ["administration", "meeting"], True),
    # Air compressor
    "450": ("procedure", ["safety", "sop", "machinery"], False),
}

# Form schemas for template documents.
# Each defines the fields for ONE FormEntry row.
# Field types: text, textarea, date, boolean, number, select
FORM_SCHEMAS = {
    # Inspection/Maintenance
    "108": {
        "fields": [
            {
                "key": "equipment_name",
                "label": "Equipment Name",
                "type": "text",
                "required": True,
            },
            {
                "key": "fault_description",
                "label": "Fault Description",
                "type": "textarea",
            },
            {"key": "repair_action", "label": "Repair Action", "type": "textarea"},
            {"key": "repair_date", "label": "Repair Date", "type": "date"},
            {"key": "signed_off_by", "label": "Signed Off By", "type": "text"},
        ]
    },
    "110": {
        "fields": [
            {
                "key": "ladder_id",
                "label": "Ladder ID",
                "type": "text",
                "required": True,
            },
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
            {
                "key": "machine_name",
                "label": "Machine Name",
                "type": "text",
                "required": True,
            },
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
    # Machine Inspection Checklists (monthly grid)
    "151b": {
        "fields": [
            {
                "key": "month",
                "label": "Month",
                "type": "select",
                "options": [
                    "Jan",
                    "Feb",
                    "Mar",
                    "Apr",
                    "May",
                    "Jun",
                    "Jul",
                    "Aug",
                    "Sep",
                    "Oct",
                    "Nov",
                    "Dec",
                ],
            },
            {"key": "inspected", "label": "Inspected", "type": "boolean"},
            {"key": "inspector", "label": "Inspector", "type": "text"},
            {"key": "notes", "label": "Notes", "type": "textarea"},
        ]
    },
    "153b": {
        "fields": [
            {
                "key": "month",
                "label": "Month",
                "type": "select",
                "options": [
                    "Jan",
                    "Feb",
                    "Mar",
                    "Apr",
                    "May",
                    "Jun",
                    "Jul",
                    "Aug",
                    "Sep",
                    "Oct",
                    "Nov",
                    "Dec",
                ],
            },
            {"key": "inspected", "label": "Inspected", "type": "boolean"},
            {"key": "inspector", "label": "Inspector", "type": "text"},
            {"key": "notes", "label": "Notes", "type": "textarea"},
        ]
    },
    "168b": {
        "fields": [
            {
                "key": "month",
                "label": "Month",
                "type": "select",
                "options": [
                    "Jan",
                    "Feb",
                    "Mar",
                    "Apr",
                    "May",
                    "Jun",
                    "Jul",
                    "Aug",
                    "Sep",
                    "Oct",
                    "Nov",
                    "Dec",
                ],
            },
            {"key": "inspected", "label": "Inspected", "type": "boolean"},
            {"key": "inspector", "label": "Inspector", "type": "text"},
            {"key": "notes", "label": "Notes", "type": "textarea"},
        ]
    },
    # Registers
    "112": {
        "fields": [
            {
                "key": "staff_name",
                "label": "Staff Name",
                "type": "text",
                "required": True,
            },
            {
                "key": "item_issued",
                "label": "Item Issued",
                "type": "text",
                "required": True,
            },
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
    # First Aid Inventories
    "113": {
        "fields": [
            {
                "key": "truck_number",
                "label": "Truck Number",
                "type": "text",
                "required": True,
            },
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
            {
                "key": "responsible_person",
                "label": "Responsible Person",
                "type": "text",
            },
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
            {
                "key": "persons_involved",
                "label": "Persons Involved",
                "type": "textarea",
            },
            {"key": "immediate_cause", "label": "Immediate Cause", "type": "textarea"},
            {"key": "root_cause", "label": "Root Cause", "type": "textarea"},
            {
                "key": "corrective_actions",
                "label": "Corrective Actions",
                "type": "textarea",
            },
            {"key": "completed_by", "label": "Completed By", "type": "text"},
            {"key": "review_date", "label": "Review Date", "type": "date"},
        ]
    },
    "205": {
        "fields": [
            {
                "key": "employee_name",
                "label": "Employee Name",
                "type": "text",
                "required": True,
            },
            {
                "key": "injury_description",
                "label": "Injury Description",
                "type": "textarea",
            },
            {"key": "week_number", "label": "Week Number", "type": "number"},
            {"key": "duties", "label": "Duties", "type": "textarea"},
            {"key": "restrictions", "label": "Restrictions", "type": "textarea"},
            {"key": "review_date", "label": "Review Date", "type": "date"},
            {"key": "supervisor", "label": "Supervisor", "type": "text"},
        ]
    },
    # Training Sign-offs
    "252": {
        "fields": [
            {
                "key": "staff_name",
                "label": "Staff Name",
                "type": "text",
                "required": True,
            },
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "trainer", "label": "Trainer", "type": "text"},
            {
                "key": "signature_confirmed",
                "label": "Signature Confirmed",
                "type": "boolean",
            },
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
            {
                "key": "staff_name",
                "label": "Staff Name",
                "type": "text",
                "required": True,
            },
            {"key": "sop_number", "label": "SOP Number", "type": "text"},
            {"key": "sop_title", "label": "SOP Title", "type": "text"},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {
                "key": "signature_confirmed",
                "label": "Signature Confirmed",
                "type": "boolean",
            },
        ]
    },
    "256": {
        "fields": [
            {
                "key": "staff_name",
                "label": "Staff Name",
                "type": "text",
                "required": True,
            },
            {"key": "sop_number", "label": "SOP Number", "type": "text"},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "trainer", "label": "Trainer", "type": "text"},
            {
                "key": "signature_confirmed",
                "label": "Signature Confirmed",
                "type": "boolean",
            },
        ]
    },
    "257": {
        "fields": [
            {
                "key": "staff_name",
                "label": "Staff Name",
                "type": "text",
                "required": True,
            },
            {"key": "sop_number", "label": "SOP Number", "type": "text"},
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "trainer", "label": "Trainer", "type": "text"},
            {
                "key": "signature_confirmed",
                "label": "Signature Confirmed",
                "type": "boolean",
            },
        ]
    },
    "258": {
        "fields": [
            {
                "key": "staff_name",
                "label": "Staff Name",
                "type": "text",
                "required": True,
            },
            {"key": "date_completed", "label": "Date Completed", "type": "date"},
            {"key": "trainer", "label": "Trainer", "type": "text"},
            {
                "key": "signature_confirmed",
                "label": "Signature Confirmed",
                "type": "boolean",
            },
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
            {
                "key": "agenda_item",
                "label": "Agenda Item",
                "type": "text",
                "required": True,
            },
            {"key": "discussion", "label": "Discussion", "type": "textarea"},
            {"key": "action", "label": "Action", "type": "textarea"},
            {
                "key": "responsible_person",
                "label": "Responsible Person",
                "type": "text",
            },
            {"key": "due_date", "label": "Due Date", "type": "date"},
        ]
    },
    "416": {
        "fields": [
            {
                "key": "agenda_item",
                "label": "Agenda Item",
                "type": "text",
                "required": True,
            },
            {"key": "presenter", "label": "Presenter", "type": "text"},
            {"key": "notes", "label": "Notes", "type": "textarea"},
        ]
    },
    "417": {
        "fields": [
            {
                "key": "staff_name",
                "label": "Staff Name",
                "type": "text",
                "required": True,
            },
            {"key": "present", "label": "Present", "type": "boolean"},
            {
                "key": "signature_confirmed",
                "label": "Signature Confirmed",
                "type": "boolean",
            },
        ]
    },
    # Emergency
    "404": {
        "fields": [
            {
                "key": "time_started",
                "label": "Time Started",
                "type": "text",
                "required": True,
            },
            {"key": "time_completed", "label": "Time Completed", "type": "text"},
            {"key": "assembly_point", "label": "Assembly Point", "type": "text"},
            {"key": "all_accounted", "label": "All Accounted For", "type": "boolean"},
            {"key": "issues", "label": "Issues", "type": "textarea"},
            {"key": "conducted_by", "label": "Conducted By", "type": "text"},
        ]
    },
}

# Regex to extract doc number from filenames like "Doc.350", "Doc 350", "Doc.350a"
DOC_NUMBER_RE = re.compile(r"Doc\.?\s*(\d+[ab]?)", re.IGNORECASE)

# Folder names to skip entirely
SKIP_FOLDERS = {"zMSM Old Docs", "zPauls Folder", "Archive"}


def _should_skip_folder(folder_name: str) -> bool:
    """Return True if this folder should be excluded from scanning."""
    if folder_name in SKIP_FOLDERS:
        return True
    if folder_name.startswith("z"):
        return True
    return False


def _extract_doc_info(filename: str) -> tuple:
    """
    Extract doc number and title from a filename.

    Returns:
        (doc_number, title) or (None, None) if no match.
    """
    match = DOC_NUMBER_RE.search(filename)
    if not match:
        return None, None

    doc_number = match.group(1)

    # Extract title: everything after the doc number pattern, minus the extension
    stem = Path(filename).stem
    # Find where the doc number pattern ends in the stem
    title_start = match.end()
    # Adjust for the stem (no extension)
    if title_start <= len(stem):
        title = stem[title_start:].strip()
        # Clean up common prefixes/separators
        title = title.lstrip(".-_ ")
    else:
        title = stem

    if not title:
        title = f"Document {doc_number}"

    return doc_number, title


class Command(BaseCommand):
    help = "Import Dropbox Health & Safety documents into Procedure/Form records"

    def add_arguments(self, parser):
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
            help="Path to Google service account JSON key file (overrides default)",
        )
        parser.add_argument(
            "--impersonate",
            help="Email address to impersonate via domain-wide delegation "
            "(e.g. office@morrissheetmetal.co.nz)",
        )

    def handle(self, *args, **options):
        folder_path = Path(options["folder"])
        dry_run = options["dry_run"]
        self._credentials_file = options.get("credentials")
        self._impersonate_email = options.get("impersonate")

        if not folder_path.exists():
            raise CommandError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise CommandError(f"Path is not a directory: {folder_path}")

        # Load company config — needed for Google Drive folder IDs
        company = CompanyDefaults.get_solo()

        if not dry_run and not company.gdrive_reference_library_folder_id:
            raise CommandError(
                "CompanyDefaults.gdrive_reference_library_folder_id is not configured. "
                "Set it in Settings before uploading."
            )

        # Phase 1: discover all candidate files
        candidates = self._discover_files(folder_path)

        # Phase 2: resolve duplicates (prefer .doc over .docx for same doc number)
        resolved = self._resolve_duplicates(candidates)

        # Phase 3: filter out already-imported documents
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

        imported_count = 0
        skipped_existing = 0
        skipped_no_mapping = 0

        for doc_number in sorted(resolved.keys(), key=lambda x: x.zfill(5)):
            file_path, title = resolved[doc_number]

            if doc_number in existing_numbers:
                skipped_existing += 1
                self.stdout.write(
                    f'  Skipped Doc.{doc_number} "{title}" (already exists)'
                )
                continue

            if doc_number not in DOC_MAPPING:
                skipped_no_mapping += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'  Skipped Doc.{doc_number} "{title}" (no mapping)'
                    )
                )
                continue

            doc_type, tags, _is_form = DOC_MAPPING[doc_number]
            path_label = "[FORM]" if doc_type in ("form", "register") else "[GDOC]"

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] {path_label} Doc.{doc_number} "
                    f'"{title}" -> {doc_type} {tags}'
                )
                imported_count += 1
                continue

            # Backdate created_at to preserve original file creation date
            file_ctime = datetime.fromtimestamp(
                file_path.stat().st_ctime, tz=timezone.utc
            )

            if doc_type in ("form", "register"):
                # Form/register — Django only, no Google Doc
                schema = FORM_SCHEMAS.get(doc_number, {})
                doc = Form.objects.create(
                    document_type=doc_type,
                    tags=tags,
                    status="active",
                    document_number=doc_number,
                    title=title,
                    form_schema=schema,
                )
                Form.objects.filter(pk=doc.pk).update(created_at=file_ctime)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'{path_label} Imported Doc.{doc_number} "{title}" '
                        f"-> {doc_type} {tags}"
                    )
                )
            else:
                # Prose docs (procedure/reference) — upload to Google Drive
                google_doc_id, google_doc_url = self._upload_to_google_docs(
                    file_path,
                    f"Doc.{doc_number} {title}",
                    company.gdrive_reference_library_folder_id,
                )
                doc = Procedure.objects.create(
                    document_type=doc_type,
                    tags=tags,
                    status="active",
                    document_number=doc_number,
                    title=title,
                    site_location="",
                    google_doc_id=google_doc_id,
                    google_doc_url=google_doc_url,
                )
                Procedure.objects.filter(pk=doc.pk).update(created_at=file_ctime)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'{path_label} Imported Doc.{doc_number} "{title}" '
                        f"-> {doc_type} {tags} ({google_doc_url})"
                    )
                )

            imported_count += 1

        # Summary
        self.stdout.write("")
        action = "Would import" if dry_run else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {imported_count} documents, "
                f"skipped {skipped_existing} (already exist), "
                f"skipped {skipped_no_mapping} (no mapping)"
            )
        )

    def _discover_files(self, folder_path: Path) -> dict:
        """
        Walk folder recursively finding .doc/.docx files with Doc.NNN pattern.

        Returns:
            dict mapping doc_number -> list of (file_path, title) tuples
        """
        candidates = {}

        for file_path in folder_path.rglob("*"):
            # Skip non-files
            if not file_path.is_file():
                continue

            # Skip .lnk files (Windows shortcuts)
            if file_path.suffix.lower() == ".lnk":
                continue

            # Skip non-doc files
            if file_path.suffix.lower() not in (".doc", ".docx"):
                continue

            # Check if any parent folder should be skipped
            if self._is_in_skip_folder(file_path, folder_path):
                continue

            doc_number, title = _extract_doc_info(file_path.name)
            if not doc_number:
                continue

            if doc_number not in candidates:
                candidates[doc_number] = []
            candidates[doc_number].append((file_path, title))

        return candidates

    def _is_in_skip_folder(self, file_path: Path, root: Path) -> bool:
        """Check if file is inside a folder that should be skipped."""
        relative = file_path.relative_to(root)
        for part in relative.parts[:-1]:  # Check all parent folder names, not the file
            if _should_skip_folder(part):
                return True
        return False

    def _resolve_duplicates(self, candidates: dict) -> dict:
        """
        Resolve duplicate doc numbers: prefer .doc over .docx.

        Returns:
            dict mapping doc_number -> (file_path, title)
        """
        resolved = {}

        for doc_number, file_list in candidates.items():
            if len(file_list) == 1:
                resolved[doc_number] = file_list[0]
                continue

            # Prefer .doc over .docx
            doc_files = [f for f in file_list if f[0].suffix.lower() == ".doc"]
            docx_files = [f for f in file_list if f[0].suffix.lower() == ".docx"]

            if doc_files:
                # If multiple .doc files, pick the one with the latest mtime
                best = max(doc_files, key=lambda f: f[0].stat().st_mtime)
            elif docx_files:
                best = max(docx_files, key=lambda f: f[0].stat().st_mtime)
            else:
                best = file_list[0]

            resolved[doc_number] = best

        return resolved

    def _get_drive_service(self):
        """Get a Google Drive service, optionally with custom credentials."""
        if self._credentials_file:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            scopes = [
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/documents",
            ]
            creds = service_account.Credentials.from_service_account_file(
                self._credentials_file, scopes=scopes
            )
            if self._impersonate_email:
                creds = creds.with_subject(self._impersonate_email)
            return build("drive", "v3", credentials=creds, cache_discovery=False)

        from apps.job.importers.google_sheets import _svc

        return _svc("drive", "v3")

    def _upload_to_google_docs(
        self, file_path: Path, title: str, folder_id: str
    ) -> tuple:
        """
        Upload a .doc/.docx file to Google Drive, converting to Google Docs format.

        Returns:
            (doc_id, edit_url)
        """
        from googleapiclient.http import MediaFileUpload

        drive_service = self._get_drive_service()

        ext = file_path.suffix.lower()
        mime_types = {
            ".docx": (
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
            ".doc": "application/msword",
        }
        mime_type = mime_types.get(ext, "application/octet-stream")

        # Preserve original times from Dropbox
        stat = file_path.stat()
        created_time = datetime.fromtimestamp(
            stat.st_ctime, tz=timezone.utc
        ).isoformat()
        modified_time = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat()

        media = MediaFileUpload(str(file_path), mimetype=mime_type)
        file_metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id],
            "createdTime": created_time,
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
