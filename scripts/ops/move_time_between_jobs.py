#!/usr/bin/env python
"""Move all actual timesheet time entries from one job to another.

Moves CostLine rows (kind="time", created_from_timesheet) from the source
job's actual cost set to the target job's newest actual cost set. Dry run by
default; nothing changes without --execute.

Usage:
    uv run python -m scripts.ops.move_time_between_jobs --from 96881 --to 96882            # dry run
    uv run python -m scripts.ops.move_time_between_jobs --from 96881 --to 96882 --execute  # apply
"""

import argparse
import logging
import sys

from scripts.bootstrap import setup_django

setup_django()

from django.db import transaction  # noqa: E402 -- Django must be configured first

from apps.job.models import CostLine, CostSet, Job  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Move time entries between jobs")
    parser.add_argument(
        "--from", dest="from_job", type=int, required=True, help="Source job number"
    )
    parser.add_argument("--to", dest="to_job", type=int, required=True, help="Target job number")
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is dry run)")
    args = parser.parse_args()

    mode = "EXECUTE" if args.execute else "DRY RUN"
    logger.info(
        "=== Move time entries from Job %s to Job %s [%s] ===",
        args.from_job,
        args.to_job,
        mode,
    )

    source_job = Job.objects.get(job_number=args.from_job)
    target_job = Job.objects.get(job_number=args.to_job)
    logger.info("Source: Job %s - %s", source_job.job_number, source_job.name)
    logger.info("Target: Job %s - %s", target_job.job_number, target_job.name)

    # The newest actual cost set is where new timesheet entries land, so it is
    # where moved entries belong too.
    target_cs = CostSet.objects.filter(job=target_job, kind="actual").order_by("-rev").first()
    if not target_cs:
        logger.error("No 'actual' cost set found on Job %s", args.to_job)
        sys.exit(1)
    logger.info("Target cost set: %s", target_cs.id)

    lines = list(
        CostLine.objects.filter(
            cost_set__job=source_job,
            cost_set__kind="actual",
            kind="time",
            meta__created_from_timesheet=True,
        ).order_by("created_at")
    )

    if not lines:
        logger.info("No actual timesheet time entries found on source job.")
        sys.exit(0)

    logger.info("Found %d time entries to move:", len(lines))
    for cl in lines:
        logger.info(
            "  %s | desc: %s | qty: %shr, cost: %s, rev: %s | date: %s | staff_id: %s",
            cl.id,
            cl.desc,
            cl.quantity,
            cl.unit_cost,
            cl.unit_rev,
            cl.accounting_date,
            # The staff FK is authoritative in v2; meta["staff_id"] is legacy.
            cl.staff_id,
        )

    if not args.execute:
        logger.info("DRY RUN complete. No changes made. Run with --execute to apply.")
        sys.exit(0)

    line_ids = [cl.id for cl in lines]

    with transaction.atomic():
        updated = CostLine.objects.filter(id__in=line_ids).update(cost_set_id=target_cs.id)
        logger.info("Moved %d time entries to Job %s.", updated, args.to_job)

    # Verify after commit: read each row back and refuse to report success
    # unless every line landed on the target cost set.
    for cl_id in line_ids:
        cl = CostLine.objects.get(id=cl_id)
        if cl.cost_set_id != target_cs.id:
            logger.error("VERIFICATION FAILED for %s", cl_id)
            sys.exit(1)

    logger.info("Verification passed: all lines now on target cost set.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
