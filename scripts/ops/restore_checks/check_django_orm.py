#!/usr/bin/env python
"""Test Django ORM access to restored data."""

import os
import sys
from pathlib import Path

# scripts/ops/restore_checks/ is three levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from apps.accounts.models import Staff  # noqa: E402 -- Django must be configured first
from apps.company.models import Company  # noqa: E402
from apps.job.models import Job  # noqa: E402


def main() -> int:
    print(f"Jobs: {Job.objects.count()}")
    print(f"Staff: {Staff.objects.count()}")
    print(f"Companies: {Company.objects.count()}")

    job = Job.objects.first()
    if job is None:
        print("ERROR: No jobs found")
        return 1

    print(f"Sample job: {job.name} (#{job.job_number})")
    print(f"Person: {job.person.name if job.person else 'None'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
