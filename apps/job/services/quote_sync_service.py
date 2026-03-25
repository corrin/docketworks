# filepath: apps/job/services/quote_sync_service.py
"""
Quote Sync Service

High-level API for managing quote spreadsheets integrated with Google Sheets.
Provides functionality to:
- Link jobs to Google Sheets quote templates
- Fetch data from linked sheets
- Preview and apply quote changes
"""

import logging

import pandas as pd

from apps.job.importers.google_sheets import (
    _svc,
    copy_file,
    create_folder,
    extract_file_id,
    fetch_sheet_df,
    populate_sheet_from_costset,
)
from apps.job.models import Job
from apps.job.models.spreadsheet import QuoteSpreadsheet
from apps.job.services.import_quote_service import (
    import_quote_from_drafts,
    preview_quote_import_from_drafts,
)
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)


def link_quote_sheet(job: Job, template_url: str | None = None) -> QuoteSpreadsheet:
    """
    1. Ensure the parent 'DocketWorks' folder exists inside
       CompanyDefaults.gdrive_quotes_folder_id (create if missing and update
       CompanyDefaults).
    2. Create or locate a sub-folder named '{job.job_number} – {job.name}'.
    3. Copy the template (passed in or CompanyDefaults.master_quote_template_url)
       into that folder; rename to '{job.job_number} Quote'.
    4. Create or update QuoteSpreadsheet for the job.
    5. Return the QuoteSpreadsheet instance.
    """
    logger.info(f"Linking quote sheet for job {job.job_number}")

    try:
        # Get company defaults
        company_defaults = CompanyDefaults.get_solo()
        if not company_defaults:
            raise RuntimeError("CompanyDefaults not configured")

        # Determine template URL
        if not template_url:
            template_url = company_defaults.master_quote_template_url
        if not template_url:
            raise RuntimeError(
                "No master quote template URL configured in CompanyDefaults"
            )

        # Extract template file ID
        template_file_id = extract_file_id(template_url)

        # Get or create parent folder
        quotes_folder_id = company_defaults.gdrive_quotes_folder_id
        if not quotes_folder_id:
            raise RuntimeError(
                "gdrive_quotes_folder_id not configured in CompanyDefaults"
            )

        # Ensure 'DocketWorks' folder exists
        docketworks_folder_id = _ensure_docketworks_folder(
            quotes_folder_id, company_defaults
        )

        # Create or locate job sub-folder
        job_folder_name = f"{job.job_number} – {job.name}"
        job_folder_id = _create_or_get_job_folder(
            docketworks_folder_id, job_folder_name
        )
        # Copy template to job folder
        quote_file_name = f"{job.job_number} Quote"
        quote_file_id = copy_file(template_file_id, quote_file_name, job_folder_id)

        # Create or update QuoteSpreadsheet
        quote_sheet, created = QuoteSpreadsheet.objects.get_or_create(
            job=job,
            defaults={
                "sheet_id": quote_file_id,
                "sheet_url": (
                    f"https://docs.google.com/spreadsheets/d/{quote_file_id}/edit"
                ),
                "tab": "Primary Details",
            },
        )
        if not created:
            # Update existing
            quote_sheet.sheet_id = quote_file_id
            quote_sheet.sheet_url = (
                f"https://docs.google.com/spreadsheets/d/{quote_file_id}/edit"
            )
            quote_sheet.save()

        # Pre-populate sheet with existing quote data if available
        quote_cost_set = job.latest_quote
        if quote_cost_set and quote_cost_set.cost_lines.exists():
            quote_lines_count = quote_cost_set.cost_lines.count()
            if quote_lines_count > 0:
                logger.info(
                    f"Pre-populating quote sheet with {quote_lines_count} "
                    "quote lines (priority)"
                )
                try:
                    populate_sheet_from_costset(quote_file_id, quote_cost_set)
                    logger.info(
                        "Successfully pre-populated quote sheet with quote data"
                    )
                    return quote_sheet
                except Exception as e:
                    logger.warning(
                        f"Failed to pre-populate quote sheet from quote: {str(e)} - "
                        "Sheet created but empty"
                    )
                    return quote_sheet

        # Fallback: if there's no quote cost set, try to pre-populate from estimate
        estimate_cost_set = job.latest_estimate
        if estimate_cost_set and job.latest_estimate.cost_lines.exists():
            cost_lines_count = estimate_cost_set.cost_lines.count()
            if cost_lines_count > 0:
                logger.info(
                    f"Pre-populating quote sheet with {cost_lines_count} estimate lines"
                )
                try:
                    # 1. Populate the Google Sheet
                    populate_sheet_from_costset(quote_file_id, estimate_cost_set)
                    logger.info(
                        "Successfully pre-populated quote sheet with estimate data"
                    )

                    # 2. Also copy to the quote cost set, if it exists
                    if quote_cost_set:
                        _copy_estimate_to_quote_costset(
                            estimate_cost_set, quote_cost_set
                        )
                        logger.info(
                            "Successfully copied estimate data to quote costset"
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to pre-populate quote sheet from estimate: {str(e)} - "
                        "Sheet created but empty"
                    )

        logger.info(
            f"Successfully linked quote sheet for job {job.job_number}: "
            f"{quote_sheet.sheet_url}"
        )
        return quote_sheet

    except Exception as e:
        logger.error(f"Error linking quote sheet for job {job.job_number}: {str(e)}")
        raise RuntimeError(f"Failed to link quote sheet: {str(e)}") from e


def _fetch_drafts(job: Job):
    """
    Download the linked sheet as xlsx, parse using the same Excel parser,
    and return DraftLine[].
    WARNING: THIS CODE WAS WRITTEN BY AI
    """
    logger.info(f"Fetching drafts for job {job.job_number}")

    try:
        if not job.quote_sheet:
            raise RuntimeError(f"Job {job.job_number} has no linked quote sheet")

        quote_sheet = job.quote_sheet
        sheet_id = quote_sheet.sheet_id
        tab = quote_sheet.tab or "Primary Details"

        # Download sheet data as DataFrame
        logger.info(f"About to fetch sheet data for job {job.job_number}")
        df = fetch_sheet_df(str(sheet_id), tab)

        logger.info(f"Received DataFrame with shape: {df.shape}")
        logger.info(f"DataFrame columns: {list(df.columns)}")

        if df.empty:
            logger.warning(f"Empty data from sheet {sheet_id}")
            return []

        # Log sample of data
        logger.info("Sample DataFrame data (first 3 rows):")
        for i, row in df.head(3).iterrows():
            logger.info(f"    Row {i}: {row.to_dict()}")

        # Process DataFrame directly to create DraftLine objects
        logger.info("Processing DataFrame to create draft lines...")

        # Import DraftLine here to avoid circular imports
        from apps.job.importers.draft import DraftLine, Kind

        draft_lines = []

        # Process each row in the DataFrame
        for idx, row in df.iterrows():
            try:
                # Skip rows that don't have required data
                if pd.isna(row.get("desc", "")) or row.get("desc", "").strip() == "":
                    continue

                # Extract values from row (adjust column names as needed)
                desc = str(row.get("desc", "")).strip()
                quantity = (
                    float(row.get("quantity", 0))
                    if pd.notna(row.get("quantity"))
                    else 0
                )
                unit_cost = (
                    float(row.get("unit_cost", 0))
                    if pd.notna(row.get("unit_cost"))
                    else 0
                )

                # Determine kind (labor vs material) - adjust logic as needed
                kind_str = str(row.get("kind", "")).strip().lower()
                if kind_str in ["labor", "labour"]:
                    kind = Kind.LABOR
                else:
                    kind = Kind.MATERIAL

                # Create DraftLine
                draft_line = DraftLine(
                    kind=kind, desc=desc, quantity=quantity, unit_cost=unit_cost
                )

                draft_lines.append(draft_line)

            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Skipping invalid row {idx}: {e}")
                continue

        logger.info(
            f"✅ Created {len(draft_lines)} draft lines from Google Sheets data"
        )

        # Log sample of parsed lines
        for i, line in enumerate(draft_lines[:3]):
            logger.info(f"    Draft line {i}: {line}")

        return draft_lines

    except Exception as e:
        logger.error(f"Error fetching drafts for job {job.job_number}: {str(e)}")
        raise RuntimeError(f"Failed to fetch drafts: {str(e)}") from e


def preview_quote(job: Job):
    """
    Preview quote import from linked Google Sheet.

    Args:
        job: Job instance

    Returns:
        Dictionary with preview information

    Raises:
        RuntimeError: If preview fails
    """
    logger.info(f"Previewing quote for job {job.job_number}")

    try:
        drafts = _fetch_drafts(job)
        return preview_quote_import_from_drafts(job, drafts)

    except Exception as e:
        logger.error(f"Error previewing quote for job {job.job_number}: {str(e)}")
        raise RuntimeError(f"Failed to preview quote: {str(e)}") from e


def apply_quote(job: Job):
    """
    Apply quote import from linked Google Sheet.

    Args:
        job: Job instance

    Returns:
        QuoteImportResult with operation details

    Raises:
        RuntimeError: If import fails
    """
    logger.info(f"Applying quote for job {job.job_number}")

    try:
        drafts = _fetch_drafts(job)
        result = import_quote_from_drafts(job, drafts)

        if result.success:
            logger.info(f"Successfully applied quote for job {job.job_number}")
        else:
            logger.error(
                f"Failed to apply quote for job {job.job_number}: "
                f"{result.error_message}"
            )

        return result

    except Exception as e:
        logger.error(f"Error applying quote for job {job.job_number}: {str(e)}")
        raise RuntimeError(f"Failed to apply quote: {str(e)}") from e


# ---------- helper functions ----------


def _find_folder_by_name_in_parent(folder_name: str, parent_id: str) -> str | None:
    """
    Find a folder by name within a specific parent folder.

    Args:
        folder_name: Name of the folder to find
        parent_id: ID of the parent folder to search in

    Returns:
        str | None: Folder ID if found, None otherwise
    """
    try:
        drive_service = _svc("drive", "v3")

        # Search for folder by name within specific parent
        query = (
            f"name='{folder_name}' and "
            f"'{parent_id}' in parents and "
            "mimeType='application/vnd.google-apps.folder' and "
            "trashed=false"
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
            logger.debug(
                f"Found existing folder '{folder_name}' in parent {parent_id}: {folder_id}"
            )
            return str(folder_id)

        return None

    except Exception as e:
        logger.error(
            f"Error searching for folder '{folder_name}' in parent {parent_id}: {str(e)}"
        )
        return None


def _ensure_docketworks_folder(
    parent_folder_id: str, company_defaults: CompanyDefaults
) -> str:
    """
    Ensure 'DocketWorks' folder exists in the parent folder.
    Search for existing folder by name, create if missing.

    Args:
        parent_folder_id: Parent folder ID
        company_defaults: CompanyDefaults instance

    Returns:
        str: DocketWorks folder ID
    """
    try:
        # Search for existing 'DocketWorks' folder in the parent directory
        existing_folder_id = _find_folder_by_name_in_parent(
            "DocketWorks", parent_folder_id
        )

        if existing_folder_id:
            logger.info(f"Found existing DocketWorks folder: {existing_folder_id}")
            return existing_folder_id

        # Create new 'DocketWorks' folder
        docketworks_folder_id = create_folder("DocketWorks", parent_folder_id)

        logger.info(f"Created DocketWorks folder: {docketworks_folder_id}")
        return docketworks_folder_id

    except Exception as e:
        raise RuntimeError(f"Failed to ensure DocketWorks folder: {str(e)}") from e


def _create_or_get_job_folder(parent_folder_id: str, folder_name: str) -> str:
    """
    Create or get job-specific folder.
    First search for existing folder, then create if not found.

    Args:
        parent_folder_id: Parent folder ID
        folder_name: Job folder name

    Returns:
        str: Job folder ID
    """
    try:
        # First, search for existing folder
        existing_folder_id = _find_folder_by_name_in_parent(
            folder_name, parent_folder_id
        )

        if existing_folder_id:
            logger.info(
                f"Found existing job folder '{folder_name}': {existing_folder_id}"
            )
            return existing_folder_id

        # Create new folder if not found
        job_folder_id = create_folder(folder_name, parent_folder_id)
        logger.info(f"Created new job folder '{folder_name}': {job_folder_id}")
        return job_folder_id

    except Exception as e:
        raise RuntimeError(
            f"Failed to create/get job folder '{folder_name}': {str(e)}"
        ) from e


def _copy_estimate_to_quote_costset(estimate_cost_set, quote_cost_set):
    """
    Copy cost lines from estimate to quote costset.

    Args:
        estimate_cost_set: Source estimate costset
        quote_cost_set: Target quote costset
    """
    try:
        # Import here to avoid circular imports
        from apps.job.models.costing import CostLine

        # Clear existing quote cost lines
        quote_cost_set.cost_lines.all().delete()

        # Copy cost lines from estimate to quote
        for estimate_line in estimate_cost_set.cost_lines.all():
            CostLine.objects.create(
                cost_set=quote_cost_set,
                kind=estimate_line.kind,
                desc=estimate_line.desc,
                quantity=estimate_line.quantity,
                unit_cost=estimate_line.unit_cost,
                unit_rev=estimate_line.unit_rev,
                accounting_date=estimate_line.accounting_date,
                xero_pay_item=estimate_line.xero_pay_item,
            )

        # Update quote costset totals
        quote_cost_set.calculate_totals()
        quote_cost_set.save()

        logger.info(
            f"Copied {estimate_cost_set.cost_lines.count()} lines from "
            "estimate to quote"
        )

    except Exception as e:
        logger.error(f"Error copying estimate to quote costset: {str(e)}")
        raise
