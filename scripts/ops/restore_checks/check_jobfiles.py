#!/usr/bin/env python
"""Verify every JobFile row's bytes exist under DROPBOX_WORKFLOW_FOLDER."""

import sys
from pathlib import Path

from scripts.bootstrap import setup_django

setup_django()

from django.conf import settings  # noqa: E402 -- Django must be configured first

from apps.job.models import JobFile  # noqa: E402


def main() -> int:
    root = Path(settings.DROPBOX_WORKFLOW_FOLDER)
    job_files = JobFile.objects.filter(file_path__isnull=False).exclude(file_path="")
    total_files = job_files.count()
    existing_files = 0

    for job_file in job_files:
        if (root / str(job_file.file_path)).exists():
            existing_files += 1

    missing = total_files - existing_files
    print(f"Workflow root: {root}")
    print(f"Total JobFile records with file_path: {total_files}")
    print(f"Files present on disk: {existing_files}")
    print(f"Missing files: {missing}")

    # Non-zero rather than a printed count: this runs inside the runbook's
    # check loop and verify-instance.sh, where an operator reads exit codes
    # and a wrapper reads nothing else. A row whose bytes are absent is a
    # job attachment that 404s in the application.
    if missing:
        print(f"FAIL: {missing} JobFile rows have no file under {root}.")
        # Wrong root before missing bytes: when everything is missing the
        # cause is almost never thousands of lost files — it is
        # DROPBOX_WORKFLOW_FOLDER not naming the directory that directly
        # contains the Job-* folders (2026-08-31 production incident).
        if existing_files == 0 and total_files > 0:
            print(
                "Nothing resolved: check DROPBOX_WORKFLOW_FOLDER first — it must "
                "directly contain the Job-<number> folders."
            )
        else:
            print("On a non-production restore, run recreate_jobfiles.py.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
