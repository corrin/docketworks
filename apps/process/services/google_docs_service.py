"""
GoogleDocsService - Creates and manages Google Docs for JSA/SWP/SOP documents.

Provides:
- Creating new Google Docs from AI-generated ProcessDocument content
- Reading content from existing Google Docs
- Updating existing Google Docs with new content
- Structured formatting with headers, tables, and bullet lists
- Storage in dedicated SafetyDocuments folder on Google Drive
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from googleapiclient.errors import HttpError

from apps.job.importers.google_sheets import (
    _set_public_edit_permissions,
    _svc,
    create_folder,
)
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


# Color constants (RGB values 0.0-1.0) - matching SafetyPDFService
PRIMARY_BLUE = (0.0, 0.29, 0.68)  # #004AAD - company default colour
TEXT_DARK = (0.06, 0.09, 0.16)  # #0F172A
RISK_LOW = (0.13, 0.77, 0.37)  # #22C55E - Green
RISK_MODERATE = (0.96, 0.62, 0.04)  # #F59E0B - Orange
RISK_HIGH = (0.94, 0.27, 0.27)  # #EF4444 - Red
RISK_EXTREME = (0.50, 0.11, 0.11)  # #7F1D1D - Dark red


@dataclass
class GoogleDocResult:
    """Result of Google Doc creation."""

    document_id: str
    edit_url: str


@dataclass
class ProcessDocumentContent:
    """Structured content from a process document."""

    title: str
    document_type: str  # 'jsa' or 'swp'
    description: str
    site_location: str
    ppe_requirements: list[str]
    tasks: list[dict]  # List of task dicts with hazards, controls, etc.
    additional_notes: str
    raw_text: str  # Full document text for AI processing


class GoogleDocsService:
    """Service for creating formatted Google Docs from process documents."""

    def __init__(self):
        """Initialize the service."""
        company = CompanyDefaults.get_solo()
        self.company_name = company.company_name

    def create_process_document(
        self,
        document_type: str,
        title: str,
        content: dict[str, Any],
        job: Any | None = None,
        document_number: str = "",
    ) -> GoogleDocResult:
        """
        Create a formatted Google Doc from AI-generated process document content.

        Args:
            document_type: 'jsa' or 'swp'
            title: Document title
            content: AI-generated content dict with tasks, ppe_requirements, etc.
            job: Optional Job instance (for JSAs)
            document_number: Optional document number (e.g., '307')

        Returns:
            GoogleDocResult with document_id and edit_url

        Raises:
            RuntimeError: If document creation fails
        """
        if not title:
            raise ValueError("Document must have a title")

        try:
            doc_type_labels = {"jsa": "JSA", "swp": "SWP", "sop": "SOP"}
            doc_type_label = doc_type_labels.get(document_type, "SWP")
            # Include document number in title if provided
            if document_number:
                full_title = f"{doc_type_label} {document_number} - {title}"
            else:
                full_title = f"{doc_type_label} - {title}"

            # Phase 1: Create blank document
            document_id = self._create_blank_document(full_title)
            logger.info(f"Created blank document: {document_id}")

            # Phase 2: Build and execute content requests
            requests = self._build_document_requests(document_type, title, content, job)

            if requests:
                docs_service = _svc("docs", "v1")
                docs_service.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()
                logger.info(f"Populated document with {len(requests)} requests")

            # Phase 3: Add task table if there are tasks
            tasks = content.get("tasks", [])
            if tasks:
                self._add_tasks_table(document_id, tasks)

            # Phase 4: Move to SafetyDocuments folder
            self._move_to_safety_folder(document_id)

            # Phase 5: Set public edit permissions
            _set_public_edit_permissions(document_id)

            edit_url = f"https://docs.google.com/document/d/{document_id}/edit"
            logger.info(f"Created process document: {edit_url}")

            return GoogleDocResult(document_id=document_id, edit_url=edit_url)

        except HttpError as e:
            persist_app_error(e)
            raise RuntimeError(f"Google API error: {e.reason}") from e
        except Exception as e:
            persist_app_error(e)
            raise RuntimeError(f"Failed to create Google Doc: {str(e)}") from e

    def read_document(self, document_id: str) -> ProcessDocumentContent:
        """
        Read content from an existing Google Doc.

        Args:
            document_id: Google Docs document ID

        Returns:
            ProcessDocumentContent with parsed content

        Raises:
            RuntimeError: If document cannot be read
        """
        try:
            docs_service = _svc("docs", "v1")
            doc = docs_service.documents().get(documentId=document_id).execute()

            # Extract raw text
            raw_text = self._extract_raw_text(doc)

            # Parse structured content
            content = self._parse_document_content(doc, raw_text)

            logger.info(f"Read document {document_id}: {len(raw_text)} chars")
            return content

        except HttpError as e:
            persist_app_error(e)
            raise RuntimeError(f"Failed to read Google Doc: {e.reason}") from e
        except Exception as e:
            persist_app_error(e)
            raise RuntimeError(f"Failed to read Google Doc: {str(e)}") from e

    def update_document(
        self,
        document_id: str,
        content: dict[str, Any],
    ) -> GoogleDocResult:
        """
        Update an existing Google Doc with new content.

        This replaces the entire document content with the new content.

        Args:
            document_id: Google Docs document ID
            content: New content dict with tasks, ppe_requirements, etc.

        Returns:
            GoogleDocResult with document_id and edit_url

        Raises:
            RuntimeError: If document cannot be updated
        """
        try:
            docs_service = _svc("docs", "v1")

            # Get current document to determine its type and title
            doc = docs_service.documents().get(documentId=document_id).execute()
            title = doc.get("title", "Process Document")

            # Determine document type from title
            document_type = "jsa" if "JSA" in title.upper() else "swp"

            # Get document length to clear content
            body = doc.get("body", {})
            doc_content = body.get("content", [])
            end_index = 1
            for element in doc_content:
                if "endIndex" in element:
                    end_index = element["endIndex"]

            # Clear existing content (keep at least index 1)
            if end_index > 2:
                docs_service.documents().batchUpdate(
                    documentId=document_id,
                    body={
                        "requests": [
                            {
                                "deleteContentRange": {
                                    "range": {
                                        "startIndex": 1,
                                        "endIndex": end_index - 1,
                                    }
                                }
                            }
                        ]
                    },
                ).execute()

            # Extract title from existing doc title (remove JSA/SWP prefix)
            clean_title = title
            for prefix in ["JSA - ", "SWP - ", "JSA-", "SWP-"]:
                if title.startswith(prefix):
                    clean_title = title[len(prefix) :]
                    break

            # Build and insert new content
            requests = self._build_document_requests(
                document_type, clean_title, content, job=None
            )

            if requests:
                docs_service.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()
                logger.info(f"Updated document content with {len(requests)} requests")

            # Add task table if there are tasks
            tasks = content.get("tasks", [])
            if tasks:
                self._add_tasks_table(document_id, tasks)

            edit_url = f"https://docs.google.com/document/d/{document_id}/edit"
            logger.info(f"Updated process document: {edit_url}")

            return GoogleDocResult(document_id=document_id, edit_url=edit_url)

        except HttpError as e:
            persist_app_error(e)
            raise RuntimeError(f"Failed to update Google Doc: {e.reason}") from e
        except Exception as e:
            persist_app_error(e)
            raise RuntimeError(f"Failed to update Google Doc: {str(e)}") from e

    def copy_document(self, source_doc_id: str, title: str) -> GoogleDocResult:
        """Copy a Google Doc, returning the new document's ID and URL."""
        try:
            drive_service = _svc("drive", "v3")
            copied = (
                drive_service.files()
                .copy(
                    fileId=source_doc_id,
                    body={"name": title},
                )
                .execute()
            )
            doc_id = copied["id"]
            edit_url = f"https://docs.google.com/document/d/{doc_id}/edit"
            self._move_to_safety_folder(doc_id)
            _set_public_edit_permissions(doc_id)
            return GoogleDocResult(document_id=doc_id, edit_url=edit_url)
        except HttpError as exc:
            persist_app_error(exc)
            raise RuntimeError(f"Failed to copy Google Doc: {exc.reason}") from exc
        except Exception as exc:
            persist_app_error(exc)
            raise RuntimeError(f"Failed to copy Google Doc: {str(exc)}") from exc

    def set_readonly(self, document_id: str) -> None:
        """Remove public edit permissions from a Google Doc, making it read-only."""
        drive_service = _svc("drive", "v3")
        try:
            permissions_response = (
                drive_service.permissions().list(fileId=document_id).execute()
            )
            for perm in permissions_response.get("permissions", []):
                if perm.get("role") == "writer" and perm.get("type") == "anyone":
                    drive_service.permissions().delete(
                        fileId=document_id, permissionId=perm["id"]
                    ).execute()
        except Exception as exc:
            persist_app_error(exc)
            raise

    def _extract_raw_text(self, doc: dict) -> str:
        """Extract all text content from a Google Doc."""
        text_parts: list[str] = []
        body = doc.get("body", {})
        content = body.get("content", [])

        for element in content:
            if "paragraph" in element:
                paragraph = element["paragraph"]
                for para_element in paragraph.get("elements", []):
                    if "textRun" in para_element:
                        text_parts.append(para_element["textRun"].get("content", ""))
            elif "table" in element:
                # Extract text from table cells
                table = element["table"]
                for row in table.get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        for cell_content in cell.get("content", []):
                            if "paragraph" in cell_content:
                                for para_element in cell_content["paragraph"].get(
                                    "elements", []
                                ):
                                    if "textRun" in para_element:
                                        text_parts.append(
                                            para_element["textRun"].get("content", "")
                                        )

        return "".join(text_parts)

    def _parse_document_content(
        self, doc: dict, raw_text: str
    ) -> ProcessDocumentContent:
        """Parse structured content from document."""
        title = doc.get("title", "")
        document_type = "jsa" if "JSA" in title.upper() else "swp"

        # Clean title
        clean_title = title
        for prefix in ["JSA - ", "SWP - ", "JSA-", "SWP-"]:
            if title.startswith(prefix):
                clean_title = title[len(prefix) :]
                break

        # Parse sections from raw text
        # This is a best-effort parse - actual structure may vary
        description = ""
        site_location = ""
        ppe_requirements: list[str] = []
        tasks: list[dict] = []
        additional_notes = ""

        lines = raw_text.split("\n")
        current_section = None

        for line in lines:
            line_stripped = line.strip()
            line_upper = line_stripped.upper()

            # Detect section headers
            if "DESCRIPTION" in line_upper:
                current_section = "description"
                continue
            elif "SITE LOCATION" in line_upper or "Site Location:" in line:
                if ":" in line:
                    site_location = line.split(":", 1)[1].strip()
                current_section = None
                continue
            elif "PPE" in line_upper or "PERSONAL PROTECTIVE" in line_upper:
                current_section = "ppe"
                continue
            elif "TASK" in line_upper and "BREAKDOWN" in line_upper:
                current_section = "tasks"
                continue
            elif "ADDITIONAL NOTES" in line_upper:
                current_section = "notes"
                continue
            elif any(
                x in line_upper
                for x in ["JOB SAFETY ANALYSIS", "SAFE WORK PROCEDURE", "JOB DETAILS"]
            ):
                current_section = None
                continue

            # Accumulate content based on section
            if current_section == "description" and line_stripped:
                description += line_stripped + " "
            elif current_section == "ppe" and line_stripped:
                # Remove bullet markers
                item = line_stripped.lstrip("-•● ")
                if item:
                    ppe_requirements.append(item)
            elif current_section == "notes" and line_stripped:
                additional_notes += line_stripped + " "

        return ProcessDocumentContent(
            title=clean_title.strip(),
            document_type=document_type,
            description=description.strip(),
            site_location=site_location.strip(),
            ppe_requirements=ppe_requirements,
            tasks=tasks,  # Tasks are complex - return empty, AI should re-parse
            additional_notes=additional_notes.strip(),
            raw_text=raw_text,
        )

    def _create_blank_document(self, title: str) -> str:
        """Create a blank Google Doc and return its ID."""
        docs_service = _svc("docs", "v1")

        document = docs_service.documents().create(body={"title": title}).execute()

        document_id = document.get("documentId")
        if not document_id:
            raise RuntimeError("Failed to get document ID from created document")

        return document_id

    def create_blank_in_folder(self, title: str, folder_id: str) -> GoogleDocResult:
        """
        Create a blank Google Doc in the specified folder.

        Args:
            title: Document title
            folder_id: Google Drive folder ID to place the document in

        Returns:
            GoogleDocResult with document_id and edit_url

        Raises:
            RuntimeError: If document creation fails
        """
        try:
            document_id = self._create_blank_document(title)
            self._move_to_folder(document_id, folder_id)
            _set_public_edit_permissions(document_id)
            edit_url = f"https://docs.google.com/document/d/{document_id}/edit"
            logger.info(f"Created blank document in folder: {edit_url}")
            return GoogleDocResult(document_id=document_id, edit_url=edit_url)
        except HttpError as e:
            persist_app_error(e)
            raise RuntimeError(f"Google API error: {e.reason}") from e
        except Exception as e:
            persist_app_error(e)
            raise RuntimeError(f"Failed to create Google Doc: {str(e)}") from e

    def _move_to_folder(self, document_id: str, folder_id: str) -> None:
        """Move document to the specified folder (supports shared drives)."""
        drive_service = _svc("drive", "v3")

        file = (
            drive_service.files()
            .get(
                fileId=document_id,
                fields="parents",
                supportsAllDrives=True,
            )
            .execute()
        )

        previous_parents = ",".join(file.get("parents", []))

        drive_service.files().update(
            fileId=document_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()

        logger.info(f"Moved document {document_id} to folder {folder_id}")

    def _get_or_create_safety_folder(self) -> str:
        """Get or create the SafetyDocuments folder in Drive."""
        drive_service = _svc("drive", "v3")

        query = (
            "name='SafetyDocuments' and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false"
        )
        results = (
            drive_service.files()
            .list(
                q=query,
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        folders = results.get("files", [])
        if folders:
            folder_id = folders[0]["id"]
            logger.debug(f"Found existing SafetyDocuments folder: {folder_id}")
            return folder_id

        # Create new folder
        folder_id = create_folder("SafetyDocuments")
        logger.info(f"Created SafetyDocuments folder: {folder_id}")
        return folder_id

    def _move_to_safety_folder(self, document_id: str) -> None:
        """Move document to SafetyDocuments folder."""
        try:
            drive_service = _svc("drive", "v3")
            folder_id = self._get_or_create_safety_folder()

            # Get current parents
            file = (
                drive_service.files()
                .get(fileId=document_id, fields="parents")
                .execute()
            )

            previous_parents = ",".join(file.get("parents", []))

            # Move to safety folder
            drive_service.files().update(
                fileId=document_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields="id, parents",
            ).execute()

            logger.info(f"Moved document {document_id} to SafetyDocuments folder")

        except HttpError as e:
            logger.warning(f"Failed to move document to folder: {e.reason}")
            # Non-critical, document still accessible

    def _build_document_requests(
        self,
        document_type: str,
        title: str,
        content: dict[str, Any],
        job: Any | None = None,
    ) -> list[dict]:
        """Build all batchUpdate requests for the document."""
        requests: list[dict] = []
        index = 1  # Document content starts at index 1

        # Header section
        header_reqs, index = self._build_header_section(document_type, title, index)
        requests.extend(header_reqs)

        # Job details section (JSA only)
        if document_type == "jsa" and job:
            info_reqs, index = self._build_info_section(content, job, index)
            requests.extend(info_reqs)

        # Description section
        description = content.get("description", "")
        if description:
            desc_reqs, index = self._build_description_section(description, index)
            requests.extend(desc_reqs)

        # PPE section
        ppe_list = content.get("ppe_requirements", [])
        if ppe_list:
            ppe_reqs, index = self._build_ppe_section(ppe_list, index)
            requests.extend(ppe_reqs)

        # Tasks section header (table added separately)
        tasks = content.get("tasks", [])
        if tasks:
            task_header_reqs, index = self._build_section_header(
                "TASK BREAKDOWN", index
            )
            requests.extend(task_header_reqs)

        # Additional notes section
        notes = content.get("additional_notes", "")
        if notes:
            notes_reqs, index = self._build_notes_section(notes, index)
            requests.extend(notes_reqs)

        return requests

    def _build_header_section(
        self, document_type: str, title: str, index: int
    ) -> tuple[list[dict], int]:
        """Build header section with document type, title, company, date."""
        requests: list[dict] = []

        doc_type_label = (
            "JOB SAFETY ANALYSIS" if document_type == "jsa" else "SAFE WORK PROCEDURE"
        )
        date_str = datetime.now().strftime("%d %B %Y")

        # Document type heading
        header_text = f"{doc_type_label}\n"
        reqs, index = self._insert_text_with_style(
            header_text, index, bold=True, font_size=16, color_rgb=PRIMARY_BLUE
        )
        requests.extend(reqs)

        # Title
        title_text = f"{title}\n"
        reqs, index = self._insert_text_with_style(
            title_text, index, bold=True, font_size=14
        )
        requests.extend(reqs)

        # Company and date
        meta_text = f"{self.company_name} | {date_str}\n\n"
        reqs, index = self._insert_text_with_style(meta_text, index, font_size=10)
        requests.extend(reqs)

        return requests, index

    def _build_info_section(
        self, content: dict[str, Any], job: Any, index: int
    ) -> tuple[list[dict], int]:
        """Build job information section (JSA only)."""
        requests: list[dict] = []

        # Section header
        reqs, index = self._build_section_header("JOB DETAILS", index)
        requests.extend(reqs)

        # Job details
        site_location = content.get("site_location", "To be confirmed")
        client_name = job.client.name if job.client else "N/A"

        info_lines = [
            f"Job Number: {job.job_number}",
            f"Client: {client_name}",
            f"Site Location: {site_location}",
        ]

        for line in info_lines:
            text = f"{line}\n"
            reqs, index = self._insert_text_with_style(text, index)
            requests.extend(reqs)

        # Add spacing
        reqs, index = self._insert_text_with_style("\n", index)
        requests.extend(reqs)

        return requests, index

    def _build_description_section(
        self, description: str, index: int
    ) -> tuple[list[dict], int]:
        """Build description section."""
        requests: list[dict] = []

        reqs, index = self._build_section_header("DESCRIPTION", index)
        requests.extend(reqs)

        text = f"{description}\n\n"
        reqs, index = self._insert_text_with_style(text, index)
        requests.extend(reqs)

        return requests, index

    def _build_ppe_section(
        self, ppe_list: list[str], index: int
    ) -> tuple[list[dict], int]:
        """Build PPE section with bullet list."""
        requests: list[dict] = []

        reqs, index = self._build_section_header(
            "PERSONAL PROTECTIVE EQUIPMENT (PPE)", index
        )
        requests.extend(reqs)

        # Track bullet range start
        bullet_start = index

        # Add each PPE item
        for ppe in ppe_list:
            text = f"{ppe}\n"
            reqs, index = self._insert_text_with_style(text, index)
            requests.extend(reqs)

        # Apply bullet formatting
        if ppe_list:
            requests.append(
                {
                    "createParagraphBullets": {
                        "range": {"startIndex": bullet_start, "endIndex": index},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                }
            )

        # Add spacing
        reqs, index = self._insert_text_with_style("\n", index)
        requests.extend(reqs)

        return requests, index

    def _build_notes_section(self, notes: str, index: int) -> tuple[list[dict], int]:
        """Build additional notes section."""
        requests: list[dict] = []

        reqs, index = self._build_section_header("ADDITIONAL NOTES", index)
        requests.extend(reqs)

        text = f"{notes}\n\n"
        reqs, index = self._insert_text_with_style(text, index)
        requests.extend(reqs)

        return requests, index

    def _build_section_header(
        self, header_text: str, index: int
    ) -> tuple[list[dict], int]:
        """Build a section header."""
        text = f"{header_text}\n"
        return self._insert_text_with_style(
            text, index, bold=True, font_size=12, color_rgb=PRIMARY_BLUE
        )

    def _insert_text_with_style(
        self,
        text: str,
        index: int,
        bold: bool = False,
        font_size: int = 11,
        color_rgb: tuple[float, float, float] | None = None,
    ) -> tuple[list[dict], int]:
        """
        Insert text at index with styling.

        Returns:
            Tuple of (requests list, new index after insertion)
        """
        requests: list[dict] = []
        text_length = len(text)
        end_index = index + text_length

        # Insert the text
        requests.append({"insertText": {"location": {"index": index}, "text": text}})

        # Build text style if needed
        text_style: dict[str, Any] = {}
        fields: list[str] = []

        if bold:
            text_style["bold"] = True
            fields.append("bold")

        if font_size != 11:
            text_style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
            fields.append("fontSize")

        if color_rgb:
            text_style["foregroundColor"] = {
                "color": {
                    "rgbColor": {
                        "red": color_rgb[0],
                        "green": color_rgb[1],
                        "blue": color_rgb[2],
                    }
                }
            }
            fields.append("foregroundColor")

        if fields:
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": index, "endIndex": end_index},
                        "textStyle": text_style,
                        "fields": ",".join(fields),
                    }
                }
            )

        return requests, end_index

    def _add_tasks_table(self, document_id: str, tasks: list[dict]) -> None:
        """
        Add tasks table to the document.

        Tables require a two-phase approach:
        1. Get document to find insertion point
        2. Insert table
        3. Populate cells in a separate batch
        """
        if not tasks:
            return

        try:
            docs_service = _svc("docs", "v1")

            # Get current document to find end index
            doc = docs_service.documents().get(documentId=document_id).execute()
            body = doc.get("body", {})
            content = body.get("content", [])

            # Find end of document
            end_index = 1
            for element in content:
                if "endIndex" in element:
                    end_index = element["endIndex"]

            # Insert table at end (before final newline)
            table_index = max(1, end_index - 1)

            # Table: 5 columns (Step, Task, Hazards, Controls, Risk), rows = tasks + header
            num_rows = len(tasks) + 1
            num_cols = 5

            # Insert table
            docs_service.documents().batchUpdate(
                documentId=document_id,
                body={
                    "requests": [
                        {
                            "insertTable": {
                                "rows": num_rows,
                                "columns": num_cols,
                                "location": {"index": table_index},
                            }
                        }
                    ]
                },
            ).execute()

            # Now populate the table
            self._populate_tasks_table(document_id, tasks, table_index)

        except HttpError as e:
            logger.warning(f"Failed to add tasks table: {e.reason}")
            # Non-critical - document still has other content

    def _populate_tasks_table(
        self, document_id: str, tasks: list[dict], table_start_index: int
    ) -> None:
        """Populate table cells with task data."""
        docs_service = _svc("docs", "v1")

        # Re-fetch document to get table structure
        doc = docs_service.documents().get(documentId=document_id).execute()
        body = doc.get("body", {})
        content = body.get("content", [])

        # Find the table
        table_element = None
        for element in content:
            if "table" in element:
                if element.get("startIndex", 0) >= table_start_index:
                    table_element = element
                    break

        if not table_element:
            logger.warning("Could not find table to populate")
            return

        table = table_element["table"]
        table_rows = table.get("tableRows", [])

        requests: list[dict] = []

        # Header row
        headers = ["Step", "Task", "Hazards", "Controls", "Risk"]
        if table_rows:
            header_row = table_rows[0]
            for col_idx, header_text in enumerate(headers):
                cell = header_row["tableCells"][col_idx]
                cell_content = cell.get("content", [{}])[0]
                paragraph = cell_content.get("paragraph", {})
                elements = paragraph.get("elements", [{}])
                cell_start = elements[0].get("startIndex", 0)

                if cell_start > 0:
                    requests.append(
                        {
                            "insertText": {
                                "location": {"index": cell_start},
                                "text": header_text,
                            }
                        }
                    )

        # Data rows
        for row_idx, task in enumerate(tasks, start=1):
            if row_idx >= len(table_rows):
                break

            row = table_rows[row_idx]
            cells = row.get("tableCells", [])

            # Column data
            step_num = str(task.get("step_number", row_idx))
            task_desc = task.get("description", "")[:100]  # Truncate for table
            hazards = "\n".join(f"- {h}" for h in task.get("potential_hazards", []))
            controls = "\n".join(
                f"- {c.get('measure', '')}" for c in task.get("control_measures", [])
            )
            initial_risk = task.get("initial_risk_rating", "")[:1]  # First letter
            revised_risk = task.get("revised_risk_rating", "")[:1]
            risk_text = f"{initial_risk}->{revised_risk}" if initial_risk else ""

            cell_data = [step_num, task_desc, hazards, controls, risk_text]

            for col_idx, cell_text in enumerate(cell_data):
                if col_idx >= len(cells):
                    break

                cell = cells[col_idx]
                cell_content = cell.get("content", [{}])[0]
                paragraph = cell_content.get("paragraph", {})
                elements = paragraph.get("elements", [{}])
                cell_start = elements[0].get("startIndex", 0)

                if cell_start > 0 and cell_text:
                    requests.append(
                        {
                            "insertText": {
                                "location": {"index": cell_start},
                                "text": cell_text,
                            }
                        }
                    )

        # Execute cell population
        if requests:
            # Insert in reverse order to avoid index shifting
            requests.reverse()
            docs_service.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()
            logger.info(f"Populated table with {len(tasks)} tasks")
