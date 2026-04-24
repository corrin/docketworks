"""Regenerate both committed golden PDFs.

Run manually after a deliberate change to the PDF rendering code::

    python scripts/regen_golden_pdfs.py

The output is compared byte-for-byte by
``apps/job/tests/test_pdf_goldens.py``. The script connects to the dev
database, builds the deterministic fixture job inside a transaction,
renders both PDFs, and rolls back — so it is idempotent and leaves no
persisted state.
"""

import logging
import os
import shutil
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

django.setup()

from django.conf import settings  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from freezegun import freeze_time  # noqa: E402
from reportlab import rl_config  # noqa: E402

from apps.accounts.models import Staff  # noqa: E402
from apps.job.services.delivery_docket_service import (  # noqa: E402
    generate_delivery_docket,
)
from apps.job.services.workshop_pdf_service import create_workshop_pdf  # noqa: E402
from apps.job.tests._pdf_golden_fixtures import (  # noqa: E402
    FROZEN_NOW,
    GOLDEN_WORKFLOW_FOLDER,
    build_golden_job,
)

GOLDENS_DIR = (
    Path(__file__).resolve().parent.parent / "apps" / "job" / "tests" / "fixtures"
)
EXPECTED_DELIVERY_DOCKET = GOLDENS_DIR / "expected_delivery_docket.pdf"
EXPECTED_WORKSHOP = GOLDENS_DIR / "expected_workshop.pdf"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("regen_golden_pdfs")


def main() -> None:
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)

    shutil.rmtree(GOLDEN_WORKFLOW_FOLDER, ignore_errors=True)
    prev_workflow = settings.DROPBOX_WORKFLOW_FOLDER
    prev_invariant = rl_config.invariant

    settings.DROPBOX_WORKFLOW_FOLDER = GOLDEN_WORKFLOW_FOLDER
    rl_config.invariant = 1

    try:
        with freeze_time(FROZEN_NOW):
            with transaction.atomic():
                test_staff, _ = Staff.objects.get_or_create(
                    email="golden-regen@example.com",
                    defaults={
                        "first_name": "Golden",
                        "last_name": "Regen",
                        "is_workshop_staff": False,
                        "is_office_staff": False,
                    },
                )

                job = build_golden_job(test_staff)

                delivery_bytes = generate_delivery_docket(job, staff=test_staff)[
                    0
                ].getvalue()
                workshop_bytes = create_workshop_pdf(job).getvalue()

                transaction.set_rollback(True)
    finally:
        settings.DROPBOX_WORKFLOW_FOLDER = prev_workflow
        rl_config.invariant = prev_invariant
        shutil.rmtree(GOLDEN_WORKFLOW_FOLDER, ignore_errors=True)
        connection.close()

    EXPECTED_DELIVERY_DOCKET.write_bytes(delivery_bytes)
    logger.info(
        "Wrote %s (%d bytes)",
        EXPECTED_DELIVERY_DOCKET,
        len(delivery_bytes),
    )

    EXPECTED_WORKSHOP.write_bytes(workshop_bytes)
    logger.info(
        "Wrote %s (%d bytes)",
        EXPECTED_WORKSHOP,
        len(workshop_bytes),
    )


if __name__ == "__main__":
    main()
