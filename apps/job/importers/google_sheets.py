"""
Google Sheets Integration Module

Provides utilities for interacting with Google Sheets and Drive APIs.
Includes functions for:
- Creating folders and copying files
- Extracting file IDs from URLs
- Fetching sheet data as pandas DataFrames
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from apps.job.models import Job
from apps.job.models.costing import CostSet

logger = logging.getLogger(__name__)

# Google API scopes
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents",
]

# Global credentials - initialized on first use
CREDS: Optional[service_account.Credentials] = None


def _get_credentials() -> service_account.Credentials:
    """
    Get Google API credentials from service account file.

    Returns:
        service_account.Credentials: Authenticated credentials

    Raises:
        RuntimeError: If credentials file not found or invalid
    """
    global CREDS

    if CREDS is None:
        try:
            key_file = os.getenv("GCP_CREDENTIALS")
            if not key_file:
                raise RuntimeError("GCP_CREDENTIALS environment variable not set")

            if not os.path.exists(key_file):
                raise RuntimeError(
                    f"Google service account key file not found: {key_file}"
                )

            CREDS = service_account.Credentials.from_service_account_file(
                key_file, scopes=SCOPES
            )  # type: ignore[no-untyped-call]

            logger.info(f"Google API credentials loaded from {key_file}")

        except Exception as e:
            raise RuntimeError(f"Failed to load Google API credentials: {str(e)}")

    assert CREDS is not None  # Should be set in the if block above
    return CREDS


def _svc(api: str, version: str) -> Any:
    """
    Create a Google API service client.

    Args:
        api: API name (e.g., 'drive', 'sheets')
        version: API version (e.g., 'v3', 'v4')

    Returns:
        googleapiclient.discovery.Resource: Service client

    Raises:
        RuntimeError: If service creation fails
    """
    try:
        credentials = _get_credentials()
        service = build(api, version, credentials=credentials, cache_discovery=False)
        logger.debug(f"Created {api} {version} service client")
        return service

    except Exception as e:
        raise RuntimeError(f"Failed to create {api} {version} service: {str(e)}")


def extract_file_id(url_or_id: str) -> str:
    """
    Extract Google Drive file ID from URL or return ID if already extracted.

    Args:
        url_or_id: Google Drive URL or file ID

    Returns:
        str: File ID

    Raises:
        RuntimeError: If file ID cannot be extracted
    """
    if not url_or_id:
        raise RuntimeError("URL or ID cannot be empty")

    # If it's already a file ID (no slashes or domains), return as-is
    if "/" not in url_or_id and "." not in url_or_id:
        return url_or_id

    # Extract from various Google Drive URL formats
    patterns = [
        r"/file/d/([a-zA-Z0-9-_]+)",  # /file/d/FILE_ID
        r"/spreadsheets/d/([a-zA-Z0-9-_]+)",  # /spreadsheets/d/FILE_ID
        r"id=([a-zA-Z0-9-_]+)",  # ?id=FILE_ID
        r"([a-zA-Z0-9-_]{25,})",  # Fallback: any long alphanumeric string
    ]

    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            file_id = match.group(1)
            logger.debug(f"Extracted file ID: {file_id}")
            return file_id

    raise RuntimeError(f"Could not extract file ID from: {url_or_id}")


def create_folder(name: str, parent_id: Optional[str] = None) -> str:
    """
    Create a folder in Google Drive.

    Args:
        name: Folder name
        parent_id: Optional parent folder ID

    Returns:
        str: Created folder ID

    Raises:
        RuntimeError: If folder creation fails
    """
    try:
        drive_service = _svc("drive", "v3")

        folder_metadata: Dict[str, Union[str, List[str]]] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }

        if parent_id:
            folder_metadata["parents"] = [parent_id]

        folder = (
            drive_service.files()
            .create(body=folder_metadata, fields="id", supportsAllDrives=True)
            .execute()
        )

        folder_id = folder.get("id")
        logger.info(f"Created folder '{name}' with ID: {folder_id}")
        return str(folder_id) if folder_id else ""

    except HttpError as e:
        raise RuntimeError(f"Failed to create folder '{name}': {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error creating folder '{name}': {str(e)}")


def copy_file(
    template_id: str,
    name: str,
    parent_id: Optional[str] = None,
    make_public_editable: bool = True,
) -> str:
    """
    Copy a file in Google Drive and optionally set public edit permissions.

    By default, copied files are given "anyone with the link can edit" permissions
    to enable easy sharing and collaboration. This is ideal for quote spreadsheets
    that need to be accessible to clients or external collaborators.

    Args:
        template_id: Source file ID to copy
        name: Name for the copied file
        parent_id: Optional parent folder ID
        make_public_editable: If True (default), grants
            "anyone with link can edit" permissions

    Returns:
        str: Copied file ID

    Raises:
        RuntimeError: If file copy fails
    """
    try:
        drive_service = _svc("drive", "v3")

        copy_metadata: Dict[str, Union[str, List[str]]] = {"name": name}

        if parent_id:
            copy_metadata["parents"] = [parent_id]

        copied_file = (
            drive_service.files()
            .copy(
                fileId=template_id,
                body=copy_metadata,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )

        copied_id = copied_file.get("id")

        # Set public edit permissions if requested
        if make_public_editable and copied_id:
            _set_public_edit_permissions(copied_id)

        logger.info(f"Copied file '{name}' with ID: {copied_id}")
        return str(copied_id) if copied_id else ""

    except HttpError as e:
        raise RuntimeError(f"Failed to copy file '{name}': {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error copying file '{name}': {str(e)}")


def _set_public_edit_permissions(file_id: str) -> None:
    """
    Set public edit permissions on a Google Drive file.
    Grants "anyone with the link can edit" access.

    Args:
        file_id: Google Drive file ID

    Raises:
        RuntimeError: If setting permissions fails
    """
    try:
        drive_service = _svc("drive", "v3")

        permission = {"type": "anyone", "role": "writer"}

        drive_service.permissions().create(
            fileId=file_id, body=permission, supportsAllDrives=True
        ).execute()

        logger.info(f"Set public edit permissions for file: {file_id}")

    except HttpError as e:
        logger.warning(
            f"Failed to set public permissions for file {file_id}: {e.reason}"
        )
        # Don't raise - this is not critical for file functionality
    except Exception as e:
        logger.warning(
            f"Unexpected error setting permissions for file {file_id}: {str(e)}"
        )
        # Don't raise - this is not critical for file functionality


def fetch_sheet_df(sheet_id: str, sheet_range: str = "Primary Details") -> pd.DataFrame:
    """
    Fetch data from a Google Sheet as a pandas DataFrame.

    Args:
        sheet_id: Google Sheets file ID
        sheet_range: Sheet range to fetch (default: "Primary Details")

    Returns:
        pd.DataFrame: Sheet data

    Raises:
        RuntimeError: If data fetch fails
    """
    try:
        sheets_service = _svc("sheets", "v4")

        logger.info(f"🔍 Fetching sheet data for ID: {sheet_id}, range: {sheet_range}")

        # Fetch the data
        result = (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=sheet_range)
            .execute()
        )

        values = result.get("values", [])
        logger.info(f"📊 Raw Google Sheets API response: {len(values)} rows")

        # Log first few rows for debugging
        for i, row in enumerate(values[:5]):  # Log first 5 rows
            logger.info(f"    Row {i}: {row}")

        if not values:
            logger.warning(f"⚠️ No data found in sheet {sheet_id} range {sheet_range}")
            return pd.DataFrame()

        # Convert to DataFrame
        # First row is typically headers
        if len(values) > 1:
            headers = values[0]
            data_rows = values[1:]

            logger.info(f"📋 Headers: {headers}")
            logger.info(f"📝 Data rows count: {len(data_rows)}")

            # Normalize data rows to match header count
            # Some rows might have fewer columns than headers
            normalized_rows = []
            for i, row in enumerate(data_rows):
                original_length = len(row)
                # Pad row with empty strings if it has fewer columns than headers
                while len(row) < len(headers):
                    row.append("")
                # Truncate row if it has more columns than headers
                row = row[: len(headers)]

                # Log first few normalized rows
                if i < 3:
                    logger.info(
                        f"    Data row {i}: {row} (original length: {original_length})"
                    )

                normalized_rows.append(row)

            df = pd.DataFrame(normalized_rows, columns=headers)
        else:
            # Only headers, no data
            logger.info(f"📋 Only headers found: {values[0]}")
            df = pd.DataFrame(columns=values[0])

        logger.info(f"✅ Created DataFrame with shape: {df.shape}")
        logger.info(f"📊 DataFrame columns: {list(df.columns)}")

        # Log non-empty rows
        non_empty_rows = df.dropna(how="all")
        logger.info(f"🔢 Non-empty rows in DataFrame: {len(non_empty_rows)}")

        return df

    except HttpError as e:
        logger.error(f"❌ Google Sheets API error: {e.reason}")
        raise RuntimeError(f"Failed to fetch sheet data: {e.reason}")
    except Exception as e:
        logger.error(f"❌ Unexpected error fetching sheet data: {str(e)}")
        raise RuntimeError(f"Unexpected error fetching sheet data: {str(e)}")


def copy_template_for_job(job: Job) -> tuple[str, str]:
    """
    Copy a quote template for a specific job.

    Creates a "DocketWorks" folder if it doesn't exist, then copies the template
    spreadsheet with a name following the pattern: "Job {job_number} - {job_name}"

    Args:
        job: Job instance with job_number, name, and company_defaults

    Returns:
        tuple[str, str]: (file_id, web_url) of the copied spreadsheet

    Raises:
        RuntimeError: If template copy fails or company defaults missing
    """
    try:
        from apps.workflow.models.company_defaults import CompanyDefaults

        # Get company defaults for the template
        company_defaults = CompanyDefaults.get_solo()
        if not company_defaults or not company_defaults.master_quote_template_id:
            raise RuntimeError(
                "No master quote template configured in company defaults"
            )

        template_id = extract_file_id(company_defaults.master_quote_template_id)

        # Create or find "DocketWorks" folder
        folder_id = _get_or_create_docketworks_folder()

        # Generate file name
        file_name = f"Job {job.job_number} - {job.name}"

        # Copy template
        copied_file_id = copy_file(
            template_id=template_id,
            name=file_name,
            parent_id=folder_id,
            make_public_editable=True,
        )

        # Generate web URL
        web_url = f"https://docs.google.com/spreadsheets/d/{copied_file_id}/edit"

        logger.info(f"Created quote spreadsheet for job {job.job_number}: {web_url}")
        return copied_file_id, web_url

    except Exception as e:
        logger.error(f"Failed to copy template for job {job.job_number}: {str(e)}")
        raise RuntimeError(f"Failed to copy template: {str(e)}")


def _get_or_create_docketworks_folder() -> str:
    """
    Get or create the "DocketWorks" folder in Google Drive.

    Returns:
        str: Folder ID
    """
    try:
        drive_service = _svc("drive", "v3")

        # Search for existing "DocketWorks" folder
        query = (
            "name='DocketWorks' and mimeType='application/vnd.google-apps.folder' "
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
            logger.debug(f"Found existing DocketWorks folder: {folder_id}")
            return str(folder_id) if folder_id else ""

        # Create new folder
        folder_id = create_folder("DocketWorks")
        logger.info(f"Created DocketWorks folder: {folder_id}")
        return folder_id

    except Exception as e:
        logger.error(f"Failed to get/create DocketWorks folder: {str(e)}")
        raise RuntimeError(f"Failed to access DocketWorks folder: {str(e)}")


def populate_sheet_from_costset(sheet_id: str, costset: CostSet) -> None:
    """
    Populate a Google Sheet with data from a CostSet.

    Uses Google Sheets API to write cost line data to the spreadsheet.
    Attempts to populate a worksheet named "Primary Details" if it exists,
    otherwise uses the first available sheet.

    Args:
        sheet_id: Google Sheets file ID
        costset: CostSet instance with cost_lines

    Raises:
        RuntimeError: If sheet update fails
    """
    try:
        sheets_service = _svc("sheets", "v4")

        # First, get sheet metadata to find the correct sheet/tab to update
        sheet_metadata = (
            sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        )

        # Find the "Primary Details" sheet or use the first sheet
        target_sheet_id = None
        target_sheet_name = None

        for sheet in sheet_metadata.get("sheets", []):
            sheet_props = sheet.get("properties", {})
            sheet_name = sheet_props.get("title", "")

            if sheet_name == "Primary Details":
                target_sheet_id = sheet_props.get("sheetId")
                target_sheet_name = sheet_name
                break

        # If "Primary Details" not found, use the first sheet
        if target_sheet_id is None and sheet_metadata.get("sheets"):
            first_sheet = sheet_metadata["sheets"][0]
            target_sheet_id = first_sheet["properties"]["sheetId"]
            target_sheet_name = first_sheet["properties"]["title"]

        if target_sheet_id is None:
            raise RuntimeError("No sheets found in the spreadsheet")

        logger.info(
            f"Populating sheet '{target_sheet_name}' (ID: {target_sheet_id}) "
            f"with cost data"
        )
        # Prepare data in a simpler format for batch update
        cost_lines = list(costset.cost_lines.all())
        if not cost_lines:
            logger.info(f"No cost lines to populate in sheet {sheet_id}")
            return

        # Sort cost lines by quantity in descending order for better organization
        cost_lines.sort(key=lambda line: line.quantity or 0, reverse=True)

        # Prepare values for range update (simpler than batch update)
        values = []
        for i, cost_line in enumerate(cost_lines, start=1):
            row_data = [""] * 11  # Prepare 11 columns (A-K)

            # Column A (index 0): Item number (sequential, starts from 1)
            row_data[0] = str(i)

            # Column B (index 1): Quantity
            row_data[1] = str(cost_line.quantity) if cost_line.quantity else ""

            # Column C (index 2): Description
            row_data[2] = cost_line.desc or ""

            # Type-specific fields
            if cost_line.kind == "time":
                # Column D (index 3): Labour minutes
                labour_minutes = (
                    cost_line.meta.get("labour_minutes", 0)
                    if cost_line.meta
                    else cost_line.quantity * 60
                )
                row_data[3] = str(labour_minutes) if labour_minutes else ""
            elif cost_line.kind == "material":
                # Column K (index 10): Unit cost
                row_data[10] = str(cost_line.unit_cost) if cost_line.unit_cost else ""

            values.append(row_data)

        # Update the sheet using values.update (simpler than batchUpdate)
        range_name = f"'{target_sheet_name}'!A2:K{len(values) + 1}"

        body = {"values": values, "majorDimension": "ROWS"}

        result = (
            sheets_service.spreadsheets()
            .values()
            .update(
                spreadsheetId=sheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body,
            )
            .execute()
        )

        updated_cells = result.get("updatedCells", 0)
        logger.info(
            f"Updated {updated_cells} cells in sheet {sheet_id} "
            f"from cost set {costset.id}"
        )

    except Exception as e:
        logger.error(f"Failed to populate sheet {sheet_id}: {str(e)}")
        raise RuntimeError(f"Failed to populate sheet: {str(e)}")


def export_sheet_as_xlsx(sheet_id: str, file_path: str) -> None:
    """
    Export a Google Sheet as an .xlsx file and save it to file_path.
    """
    try:
        drive_service = _svc("drive", "v3")
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        request = drive_service.files().export_media(
            fileId=sheet_id, mimeType=mime_type, supportsAllDrives=True
        )
        with open(file_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        logger.info(f"Exported Google Sheet {sheet_id} to {file_path}")
    except Exception as e:
        logger.error(f"Failed to export Google Sheet {sheet_id} as xlsx: {str(e)}")
        raise RuntimeError(f"Failed to export Google Sheet as xlsx: {str(e)}")
