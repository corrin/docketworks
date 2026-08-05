"""Byte-identical golden tests for the two user-facing PDFs.

The committed PDFs are the ReportLab output contract.

When either test fails and the change is intentional, regenerate the
golden via::

    python scripts/regen_golden_pdfs.py

Then inspect the binary diff in git (open the new golden in a PDF
viewer to confirm the visual change matches intent) and commit.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.test import override_settings
from freezegun import freeze_time
from reportlab import rl_config

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.services.delivery_docket_service import generate_delivery_docket
from apps.job.services.workshop_pdf_service import create_workshop_pdf
from apps.job.tests._pdf_golden_fixtures import (
    FROZEN_NOW,
    GOLDEN_WORKFLOW_FOLDER,
    build_golden_job,
)

pytestmark = pytest.mark.django_db

GOLDENS_DIR = Path(__file__).parent / "fixtures"
EXPECTED_DELIVERY_DOCKET = GOLDENS_DIR / "expected_delivery_docket.pdf"
EXPECTED_WORKSHOP = GOLDENS_DIR / "expected_workshop.pdf"

REGEN_HINT = (
    "If this rendering change is intentional, regenerate the golden via "
    "`python scripts/regen_golden_pdfs.py` and commit the updated file."
)


@pytest.fixture
def golden_job() -> Iterator[tuple[Job, Staff]]:
    """The deterministic golden job under frozen time and invariant ReportLab."""
    test_staff = Staff.objects.create_user(
        email="base-test-staff@example.com",
        password="testpass",
        first_name="Test",
        last_name="Staff",
        is_workshop_staff=False,
        is_office_staff=False,
    )

    prev_invariant = rl_config.invariant
    rl_config.invariant = 1
    shutil.rmtree(GOLDEN_WORKFLOW_FOLDER, ignore_errors=True)

    # Stable path — ReportLab hashes the attachment filename when embedding
    # it in the PDF, so a random tmp dir would make the workshop PDF's image
    # reference differ between runs.
    with (
        freeze_time(FROZEN_NOW),
        override_settings(DROPBOX_WORKFLOW_FOLDER=GOLDEN_WORKFLOW_FOLDER),
    ):
        job = build_golden_job(test_staff)
        yield job, test_staff

    rl_config.invariant = prev_invariant
    shutil.rmtree(GOLDEN_WORKFLOW_FOLDER, ignore_errors=True)


def test_delivery_docket_matches_golden(golden_job: tuple[Job, Staff]) -> None:
    job, test_staff = golden_job
    with freeze_time(FROZEN_NOW):
        pdf_buffer, _job_file = generate_delivery_docket(job, staff=test_staff)
    actual = pdf_buffer.getvalue()
    expected = EXPECTED_DELIVERY_DOCKET.read_bytes()
    assert actual == expected, REGEN_HINT


def test_workshop_pdf_matches_golden(golden_job: tuple[Job, Staff]) -> None:
    job, _test_staff = golden_job
    with freeze_time(FROZEN_NOW):
        pdf_buffer = create_workshop_pdf(job)
    actual = pdf_buffer.getvalue()
    expected = EXPECTED_WORKSHOP.read_bytes()
    assert actual == expected, REGEN_HINT
