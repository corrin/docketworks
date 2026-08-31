#!/usr/bin/env python
"""Verify every JobFile row's bytes exist under DROPBOX_WORKFLOW_FOLDER."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.job.models import JobFile  # noqa: E402 -- Django must be configured first
from apps.job.services.file_service import (  # noqa: E402
    job_file_full_path,
    workflow_root,
)


def main() -> int:
    # Fable: resolution goes through job_file_full_path, not a local
    # root/file_path join — the app serves through it, so a row it refuses
    # (an absolute or root-escaping file_path) must fail here too instead
    # of passing a check the endpoint will 404 or 500 on.
    root = workflow_root()
    job_files = JobFile.objects.filter(file_path__isnull=False).exclude(file_path="")
    total_files = job_files.count()
    existing_files = 0
    escaping_rows = 0

    for job_file in job_files:
        try:
            full_path = job_file_full_path(job_file)
        except ValueError:  # deliberate-swallow: counted and reported below
            escaping_rows += 1
            continue
        if full_path.exists():
            existing_files += 1

    missing = total_files - existing_files - escaping_rows
    print(f"Workflow root: {root}")
    print(f"Total JobFile records with file_path: {total_files}")
    print(f"Files present on disk: {existing_files}")
    print(f"Missing files: {missing}")
    if escaping_rows:
        print(f"Rows escaping the workflow root (data corruption): {escaping_rows}")

    # Non-zero rather than a printed count: this runs inside the runbook's
    # check loop and verify-instance.sh, where an operator reads exit codes
    # and a wrapper reads nothing else. A row whose bytes are absent is a
    # job attachment that 404s in the application.
    if missing or escaping_rows:
        print(f"FAIL: {missing + escaping_rows} JobFile rows do not serve from {root}.")
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
