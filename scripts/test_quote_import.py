#!/usr/bin/env python
"""
Test the quote import service with a real spreadsheet.

Usage:
    python scripts/test_quote_import.py --file "Quote.xlsx"
    python scripts/test_quote_import.py --file "Quote.xlsx" --job-id <uuid>
    python scripts/test_quote_import.py --file "Quote.xlsx" --preview-only
"""

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.conf import settings

from apps.client.models import Client
from apps.job.models import Job
from apps.job.services.import_quote_service import (
    QuoteImportError,
    import_quote_from_file,
    preview_quote_import,
)


def get_or_create_test_job() -> Job:
    """Get or create a test job for quote import testing."""
    test_job = Job.objects.filter(name__icontains="Quote Import Test").first()
    if test_job:
        return test_job

    client = Client.objects.first()
    if not client:
        logging.info("Creating test client...")
        client = Client.objects.create(name="Test Client", account_ref="TEST001")

    test_job = Job.objects.create(
        name="Quote Import Test Job",
        client=client,
        status="quoting",
        description="Test job for quote import service testing",
    )
    logging.info("Created test job: [Job %s] %s", test_job.job_number, test_job.name)
    return test_job


def test_preview(job: Job, file_path: str) -> None:
    """Test the preview functionality."""
    logging.info("Testing quote import preview...")

    preview_data = preview_quote_import(job, file_path)

    logging.info("Preview Results:")
    logging.info("  Can proceed: %s", preview_data.get("can_proceed", False))

    validation_report = preview_data.get("validation_report")
    if validation_report:
        total_issues = validation_report.get("summary", {}).get("total_issues", 0)
        logging.info("  Validation issues: %d", total_issues)
        if validation_report.get("critical_issues"):
            logging.info("    Critical: %d", len(validation_report["critical_issues"]))
        if validation_report.get("errors"):
            logging.info("    Errors: %d", len(validation_report["errors"]))
        if validation_report.get("warnings"):
            logging.info("    Warnings: %d", len(validation_report["warnings"]))

    draft_lines = preview_data.get("draft_lines", [])
    logging.info("  Draft lines found: %d", len(draft_lines))

    diff_preview = preview_data.get("diff_preview")
    if diff_preview:
        logging.info("  Next revision: %s", diff_preview["next_revision"])
        logging.info("  Total changes: %s", diff_preview["total_changes"])
        logging.info("    Additions: %s", diff_preview["additions_count"])
        logging.info("    Updates: %s", diff_preview["updates_count"])
        logging.info("    Deletions: %s", diff_preview["deletions_count"])

    if preview_data.get("can_proceed", False):
        logging.info("Preview successful - import can proceed")
    else:
        logging.error("Preview failed - import cannot proceed")


def test_import(job: Job, file_path: str, skip_validation: bool) -> None:
    """Test the full import functionality."""
    logging.info("Testing quote import (skip_validation=%s)...", skip_validation)

    current_quote = job.get_latest("quote")
    if current_quote:
        logging.info(
            "Current quote: Rev %s (ID: %s)", current_quote.rev, current_quote.id
        )
    else:
        logging.info("No current quote found")

    result = import_quote_from_file(job, file_path, skip_validation=skip_validation)

    if result.success:
        logging.info("Quote import successful!")
        if result.cost_set:
            logging.info(
                "  New CostSet: Rev %s (ID: %s)",
                result.cost_set.rev,
                result.cost_set.id,
            )
            logging.info("  Summary: %s", result.cost_set.summary)
            logging.info("  Cost lines: %d", result.cost_set.cost_lines.count())

        if result.diff_result:
            logging.info("  Changes applied:")
            logging.info("    Added: %d lines", len(result.diff_result.to_add))
            logging.info("    Updated: %d lines", len(result.diff_result.to_update))
            logging.info("    Deleted: %d lines", len(result.diff_result.to_delete))

        updated_job = Job.objects.get(pk=job.pk)
        latest_quote = updated_job.get_latest("quote")
        if latest_quote and latest_quote.id == result.cost_set.id:
            logging.info("  Job latest_quote pointer updated correctly")
        else:
            logging.error("  Job latest_quote pointer not updated correctly")
    else:
        logging.error("Quote import failed!")
        logging.error("  Error: %s", result.error_message)
        if result.validation_report:
            for issue in result.validation_report.get("critical_issues", []):
                logging.error("    CRITICAL: %s", issue.get("message", issue))
            for issue in result.validation_report.get("errors", []):
                logging.error("    ERROR: %s", issue.get("message", issue))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=str,
        required=True,
        help="Path to the Excel file",
    )
    parser.add_argument(
        "--job-id",
        type=str,
        help="Job ID to import quote for (default: find or create test job)",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Only preview import, do not actually import",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip spreadsheet validation during import",
    )
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = Path(settings.BASE_DIR) / file_path

    if not file_path.exists():
        logging.error("Spreadsheet not found at %s", file_path)
        sys.exit(1)

    logging.info("Testing quote import service with: %s", file_path)

    if args.job_id:
        try:
            job = Job.objects.get(pk=args.job_id)
            logging.info("Using existing job: [Job %s] %s", job.job_number, job.name)
        except Job.DoesNotExist:
            logging.error("Job with ID %s not found", args.job_id)
            sys.exit(1)
    else:
        job = get_or_create_test_job()
        logging.info("Using test job: [Job %s] %s", job.job_number, job.name)

    try:
        if args.preview_only:
            logging.info("Preview mode - no actual import will be performed")
            test_preview(job, str(file_path))
        else:
            test_import(job, str(file_path), args.skip_validation)
    except QuoteImportError as e:
        logging.error("Quote import error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
