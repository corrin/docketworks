"""Tests for the delivery-docket service.

Covers the staff attribution required on the JobEvent emitted by
``generate_delivery_docket``. Migration 0079 made ``JobEvent.staff``
``NOT NULL``; without a staff argument plumbed through, the service
fails on insert.
"""

import shutil
import tempfile
from io import BytesIO

from django.test import override_settings
from django.utils import timezone

from apps.client.models import Client
from apps.job.models import Job, JobEvent, JobFile
from apps.job.services.delivery_docket_service import generate_delivery_docket
from apps.testing import BaseTestCase


class GenerateDeliveryDocketTests(BaseTestCase):
    """``generate_delivery_docket`` must attribute its JobEvent to a staff."""

    def setUp(self):
        super().setUp()

        # Sandbox the on-disk write so tests don't touch the real Dropbox path.
        self._tmp_dropbox = tempfile.mkdtemp(prefix="dw-delivery-docket-test-")
        self._settings_override = override_settings(
            DROPBOX_WORKFLOW_FOLDER=self._tmp_dropbox
        )
        self._settings_override.enable()

        self.client_obj = Client.objects.create(
            name="Test Client",
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            client=self.client_obj,
            name="Test Delivery Job",
            description="Deliver some steel",
            staff=self.test_staff,
        )

    def tearDown(self):
        self._settings_override.disable()
        shutil.rmtree(self._tmp_dropbox, ignore_errors=True)
        super().tearDown()

    def test_generate_attributes_jobevent_to_calling_staff(self):
        """The emitted JobEvent must carry the staff who triggered the print."""
        pdf_buffer, job_file = generate_delivery_docket(self.job, staff=self.test_staff)

        self.assertIsInstance(pdf_buffer, BytesIO)
        self.assertIsInstance(job_file, JobFile)
        self.assertEqual(job_file.job_id, self.job.id)

        events = JobEvent.objects.filter(
            job=self.job, event_type="delivery_docket_generated"
        )
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.staff_id, self.test_staff.id)
        self.assertEqual(event.detail["filename"], job_file.filename)
        self.assertEqual(event.detail["file_id"], str(job_file.id))
