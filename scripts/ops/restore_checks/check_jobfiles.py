#!/usr/bin/env python
"""Verify dummy files exist for all JobFile instances."""

import os
import sys
from pathlib import Path

# scripts/ops/restore_checks/ is three levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings  # noqa: E402 -- Django must be configured first

from apps.job.models import JobFile  # noqa: E402


def main() -> int:
    job_files = JobFile.objects.filter(file_path__isnull=False).exclude(file_path="")
    total_files = job_files.count()
    existing_files = 0

    for job_file in job_files:
        dummy_path = Path(settings.DROPBOX_WORKFLOW_FOLDER) / str(job_file.file_path)
        if dummy_path.exists():
            existing_files += 1

    missing = total_files - existing_files
    print(f"Total JobFile records with file_path: {total_files}")
    print(f"Dummy files created: {existing_files}")
    print(f"Missing files: {missing}")

    # Non-zero rather than a printed count: this runs inside the runbook's
    # check loop, where an operator reads exit codes and a wrapper reads
    # nothing else. A row whose bytes are absent is a job attachment that
    # 404s in the application, so recreate_jobfiles.py has not done its job.
    if missing:
        print(f"FAIL: {missing} JobFile rows have no file on disk; run recreate_jobfiles.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
