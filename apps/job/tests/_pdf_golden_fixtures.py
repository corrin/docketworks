"""Deterministic job builder shared by golden-PDF tests and the regen script.

The golden tests compare raw PDF bytes to a committed golden file. Any
drift in the test job fails the byte comparison, so this module is the
single source of truth for every field that influences PDF output.

Callers MUST install the time-freeze and ReportLab-invariant scopes AND
point ``settings.DROPBOX_WORKFLOW_FOLDER`` at a writable directory (a
tmp dir) before calling ``build_golden_job`` — the fixture copies the
logo PNG into the workflow folder because ``JobFile.file_path`` is a
plain ``CharField`` resolved against that root by
``workshop_pdf_service._add_images_to_pdf``.
"""

from __future__ import annotations

import datetime
import os
import shutil
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings

from apps.accounts.models import Staff
from apps.client.models import Client, ClientContact
from apps.job.models import CostLine, Job, JobFile
from apps.workflow.models import CompanyDefaults

FROZEN_NOW = datetime.datetime(2026, 4, 25, 10, 30, tzinfo=ZoneInfo("Pacific/Auckland"))

# Sits above any realistic dev/prod job number so
# ``Job.generate_job_number()``'s max(starting, highest+1) always resolves
# to STARTING_JOB_NUMBER in both the empty-test-DB and the loaded-dev-DB
# cases. Keeping the two paths byte-identical is the whole point of the
# golden test.
STARTING_JOB_NUMBER = 9999999

LOGO_ATTACHMENT_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "mediafiles"
    / "app_images"
    / "docketworks_logo.png"
)

# Stable absolute path shared by the tests and the regen script.
# ReportLab derives its embedded-image resource name from the file path,
# so a randomised tmp dir would make the workshop PDF's internal image
# reference differ between the regen environment and the test
# environment, breaking byte-identity.
GOLDEN_WORKFLOW_FOLDER = "/tmp/dw-pdf-golden-workflow"


def build_golden_job(test_staff: Staff) -> Job:
    """Build the deterministic test job and return it.

    Caller must have ``freezegun.freeze_time(FROZEN_NOW)`` active and
    ``settings.DROPBOX_WORKFLOW_FOLDER`` pointing at a writable dir.
    """
    if not settings.DROPBOX_WORKFLOW_FOLDER:
        raise RuntimeError(
            "build_golden_job requires settings.DROPBOX_WORKFLOW_FOLDER "
            "to point at a writable directory (use override_settings in "
            "tests or set it directly in the regen script)."
        )

    company = CompanyDefaults.get_solo()
    company.starting_job_number = STARTING_JOB_NUMBER
    company.save()

    client = Client.objects.create(
        name="ACME Engineering Ltd",
        phone="+64 4 555 1234",
        xero_last_modified=FROZEN_NOW,
    )

    contact = ClientContact.objects.create(
        client=client,
        name="Jane Doe",
        phone="+64 21 555 5678",
    )

    job = Job.objects.create(
        client=client,
        contact=contact,
        name="Custom Bracket Fabrication",
        description=("Stainless steel mounting bracket, 200x100x5mm, 4 holes per spec"),
        notes=(
            "<p>Use 316 grade. Laser cut then fold. " "Powder coat matte black.</p>"
        ),
        delivery_date=datetime.date(2026, 5, 9),
        order_number="PO-ACME-12345",
        pricing_methodology="time_materials",
        speed_quality_tradeoff="balanced",
        staff=test_staff,
    )

    estimate = job.cost_sets.get(kind="estimate")
    CostLine.objects.create(
        cost_set=estimate,
        kind="time",
        desc="Fabrication",
        quantity=Decimal("2.00"),
        unit_cost=Decimal("32.00"),
        unit_rev=Decimal("105.00"),
        accounting_date=FROZEN_NOW.date(),
    )
    CostLine.objects.create(
        cost_set=estimate,
        kind="time",
        desc="Welding",
        quantity=Decimal("1.50"),
        unit_cost=Decimal("32.00"),
        unit_rev=Decimal("105.00"),
        accounting_date=FROZEN_NOW.date(),
    )

    actual = job.cost_sets.get(kind="actual")
    CostLine.objects.create(
        cost_set=actual,
        kind="material",
        desc="Stainless steel sheet 3mm",
        quantity=Decimal("2.50"),
        unit_cost=Decimal("0"),
        unit_rev=Decimal("0"),
        accounting_date=FROZEN_NOW.date(),
    )
    CostLine.objects.create(
        cost_set=actual,
        kind="material",
        desc="M6 fasteners",
        quantity=Decimal("12.00"),
        unit_cost=Decimal("0"),
        unit_rev=Decimal("0"),
        accounting_date=FROZEN_NOW.date(),
    )

    job_folder = Path(settings.DROPBOX_WORKFLOW_FOLDER) / f"Job-{job.job_number}"
    job_folder.mkdir(parents=True, exist_ok=True)
    attachment_dest = job_folder / "docketworks_logo.png"
    shutil.copyfile(LOGO_ATTACHMENT_SOURCE, attachment_dest)
    os.chmod(attachment_dest, 0o600)

    JobFile.objects.create(
        job=job,
        filename="docketworks_logo.png",
        file_path=f"Job-{job.job_number}/docketworks_logo.png",
        mime_type="image/png",
        print_on_jobsheet=True,
        status="active",
    )

    return job
