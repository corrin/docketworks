#!/usr/bin/env python
"""Test Django ORM access to restored data."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.accounts.models import Staff  # noqa: E402 -- Django must be configured first
from apps.company.models import Company  # noqa: E402
from apps.job.models import Job  # noqa: E402


def main() -> int:
    print(f"Jobs: {Job.objects.count()}")
    print(f"Staff: {Staff.objects.count()}")
    print(f"Companies: {Company.objects.count()}")

    # Every core table must hold rows: a restore that loses staff or
    # companies would otherwise pass this check on the job count alone, and
    # validate_restored_data cannot detect wholly missing rows.
    if not Staff.objects.exists():
        print("ERROR: No staff found")
        return 1
    if not Company.objects.exists():
        print("ERROR: No companies found")
        return 1

    job = Job.objects.first()
    if job is None:
        print("ERROR: No jobs found")
        return 1

    print(f"Sample job: {job.name} (#{job.job_number})")
    print(f"Person: {job.person.name if job.person else 'None'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
