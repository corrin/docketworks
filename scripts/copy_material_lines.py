"""
Copy material cost lines from one job's actual cost set to another.

Usage:
    python manage.py shell < scripts/copy_material_lines.py
    DRY_RUN=false python manage.py shell < scripts/copy_material_lines.py

Configuration:
    Edit SOURCE_JOB_ID and TARGET_JOB_ID below, or override via env vars.
"""

import logging
import os

from django.db import transaction
from django.utils import timezone

from apps.job.models import CostLine, CostSet, Job

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

# --- Configuration -----------------------------------------------------------
SOURCE_JOB_ID = os.environ.get("SOURCE_JOB_ID", "f96d6ba3-5b91-4dd3-9b0d-95f1351313b6")
TARGET_JOB_ID = os.environ.get("TARGET_JOB_ID", "89c64e2b-b65a-42ec-bb62-ff4991cb67df")
COST_SET_KIND = "actual"  # which cost set to copy from/to
LINE_KINDS = ["material"]  # which line kinds to copy
# -----------------------------------------------------------------------------

logger.info("%s: Copy %s lines", "DRY RUN" if DRY_RUN else "LIVE RUN", LINE_KINDS)
logger.info("  Source job: %s", SOURCE_JOB_ID)
logger.info("  Target job: %s", TARGET_JOB_ID)
logger.info("=" * 70)

try:
    with transaction.atomic():
        source_job = Job.objects.get(id=SOURCE_JOB_ID)
        target_job = Job.objects.get(id=TARGET_JOB_ID)

        logger.info("Source: %s", source_job.name)
        logger.info("Target: %s", target_job.name)

        source_cs = CostSet.objects.get(job=source_job, kind=COST_SET_KIND)
        target_cs = CostSet.objects.get(job=target_job, kind=COST_SET_KIND)

        source_lines = CostLine.objects.filter(
            cost_set=source_cs, kind__in=LINE_KINDS
        ).order_by("id")

        if not source_lines.exists():
            logger.info("No matching lines found in source. Nothing to do.")

        # Check for duplicates already in target
        existing_descs = set(
            CostLine.objects.filter(
                cost_set=target_cs, kind__in=LINE_KINDS
            ).values_list("desc", flat=True)
        )

        logger.info("Source has %d lines to copy:", source_lines.count())
        created = []
        skipped = []

        for line in source_lines:
            if line.desc in existing_descs:
                skipped.append(line)
                logger.info("  SKIP (already exists): %s", line.desc)
                continue

            now = timezone.now()
            new_line = CostLine(
                cost_set=target_cs,
                kind=line.kind,
                desc=line.desc,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                unit_rev=line.unit_rev,
                meta=dict(line.meta) if line.meta else {},
                ext_refs=dict(line.ext_refs) if line.ext_refs else {},
                accounting_date=now.date(),
            )
            new_line.save()
            created.append(new_line)
            logger.info(
                "  CREATE: %s | qty=%s | cost=$%s | rev=$%s",
                line.desc,
                line.quantity,
                line.unit_cost,
                line.unit_rev,
            )

        logger.info("Summary: %d created, %d skipped", len(created), len(skipped))

        if DRY_RUN:
            logger.info("DRY RUN - rolling back.")
            raise RuntimeError("DRY RUN rollback")
        else:
            logger.info("Changes committed.")

except RuntimeError as e:
    if "DRY RUN rollback" in str(e):
        logger.info("No changes made.")
    else:
        raise
