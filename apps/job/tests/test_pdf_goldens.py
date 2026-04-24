"""Byte-identical golden tests for the two user-facing PDFs.

When either test fails and the change is intentional, regenerate the
golden via::

    python scripts/regen_golden_pdfs.py

Then inspect the binary diff in git (open the new golden in a PDF
viewer to confirm the visual change matches intent) and commit.
"""

import shutil
from pathlib import Path

from django.test import override_settings
from freezegun import freeze_time
from reportlab import rl_config

from apps.job.services.delivery_docket_service import generate_delivery_docket
from apps.job.services.workshop_pdf_service import create_workshop_pdf
from apps.job.tests._pdf_golden_fixtures import (
    FROZEN_NOW,
    GOLDEN_WORKFLOW_FOLDER,
    build_golden_job,
)
from apps.testing import BaseTestCase

GOLDENS_DIR = Path(__file__).parent / "fixtures"
EXPECTED_DELIVERY_DOCKET = GOLDENS_DIR / "expected_delivery_docket.pdf"
EXPECTED_WORKSHOP = GOLDENS_DIR / "expected_workshop.pdf"

REGEN_HINT = (
    "If this rendering change is intentional, regenerate the golden via "
    "`python scripts/regen_golden_pdfs.py` and commit the updated file."
)


class PDFGoldenTests(BaseTestCase):
    """PDF bytes must match the committed golden exactly."""

    def setUp(self):
        super().setUp()

        self._freezer = freeze_time(FROZEN_NOW)
        self._freezer.start()
        self.addCleanup(self._freezer.stop)

        self._prev_invariant = rl_config.invariant
        rl_config.invariant = 1
        self.addCleanup(lambda: setattr(rl_config, "invariant", self._prev_invariant))

        # Stable path — ReportLab hashes the attachment filename when
        # embedding it in the PDF, so a random tmp dir would make the
        # workshop PDF's image reference differ between runs.
        shutil.rmtree(GOLDEN_WORKFLOW_FOLDER, ignore_errors=True)
        self.addCleanup(
            lambda: shutil.rmtree(GOLDEN_WORKFLOW_FOLDER, ignore_errors=True)
        )

        self._settings_override = override_settings(
            DROPBOX_WORKFLOW_FOLDER=GOLDEN_WORKFLOW_FOLDER
        )
        self._settings_override.enable()
        self.addCleanup(self._settings_override.disable)

        self.job = build_golden_job(self.test_staff)

    def test_delivery_docket_matches_golden(self):
        pdf_buffer, _job_file = generate_delivery_docket(
            self.job, staff=self.test_staff
        )
        actual = pdf_buffer.getvalue()
        expected = EXPECTED_DELIVERY_DOCKET.read_bytes()
        self.assertEqual(actual, expected, msg=REGEN_HINT)

    def test_workshop_pdf_matches_golden(self):
        pdf_buffer = create_workshop_pdf(self.job)
        actual = pdf_buffer.getvalue()
        expected = EXPECTED_WORKSHOP.read_bytes()
        self.assertEqual(actual, expected, msg=REGEN_HINT)
