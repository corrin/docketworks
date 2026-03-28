#!/usr/bin/env python
"""
Fix production data issues.

Provides various fixes for known data issues that can occur in production.
Each fix is idempotent and safe to run multiple times.

Usage:
    python scripts/production_data_fixer.py --fix-empty-notes --dry-run
    python scripts/production_data_fixer.py --fix-empty-notes --live
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jobs_manager.settings")

import django

django.setup()

from django.db import transaction

from apps.job.models import Job

logger = logging.getLogger(__name__)


def fix_empty_string_notes(dry_run, verbose):
    """
    Fix jobs with empty string notes by converting them to NULL.

    This fixes the 412 Precondition Failed error that occurs when the frontend
    expects NULL but the backend has an empty string.
    """
    logger.info("Fixing empty string notes...")

    affected_jobs = Job.objects.filter(notes="")
    count = affected_jobs.count()

    if count == 0:
        logger.info("No jobs with empty string notes found. Nothing to fix.")
        return

    logger.info("Found %d jobs with empty string notes", count)

    if verbose or dry_run:
        job_list = affected_jobs.values_list("id", "job_number")
        logger.info("Affected jobs:")
        for job_id, job_number in job_list:
            logger.info("  Job #%s (ID: %s)", job_number, job_id)

    if dry_run:
        logger.info("DRY RUN: Would update %d jobs from empty string to NULL", count)
        return

    with transaction.atomic():
        updated = affected_jobs.update(notes=None)
        logger.info("Updated %d jobs from empty string to NULL", updated)

        remaining = Job.objects.filter(notes="").count()
        if remaining == 0:
            logger.info("Verification passed: No jobs with empty string notes remain")
        else:
            logger.warning("WARNING: %d jobs still have empty string notes", remaining)


def main():
    parser = argparse.ArgumentParser(description="Fix production data issues")
    parser.add_argument(
        "--fix-empty-notes",
        action="store_true",
        help="Convert empty string notes to NULL for jobs (fixes 412 errors)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be fixed without making changes (default)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually apply the fixes",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information about each fix",
    )

    args = parser.parse_args()
    dry_run = not args.live

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    if not args.fix_empty_notes:
        parser.error("No fix specified. Use --help to see available fixes.")

    if args.fix_empty_notes:
        fix_empty_string_notes(dry_run, args.verbose)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
