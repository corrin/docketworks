import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job
from apps.testing import BaseAPITestCase


class JobFilesApiTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self._tmp_dropbox = tempfile.mkdtemp(prefix="dw-job-files-api-test-")
        self._settings_override = override_settings(
            DROPBOX_WORKFLOW_FOLDER=self._tmp_dropbox
        )
        self._settings_override.enable()

        self.office_staff = Staff.objects.create_user(
            email="job-files-office@example.com",
            password="testpass",
            first_name="Office",
            last_name="Staff",
            is_office_staff=True,
            is_workshop_staff=False,
        )
        self.client_obj = Client.objects.create(
            name="Job Files Client",
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            client=self.client_obj,
            name="Attachment API Job",
            staff=self.test_staff,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.office_staff)

    def tearDown(self):
        self._settings_override.disable()
        shutil.rmtree(self._tmp_dropbox, ignore_errors=True)
        super().tearDown()

    def test_upload_returns_full_job_file_and_file_is_immediately_available(self):
        payload = b"job attachment contents"
        file_obj = SimpleUploadedFile(
            "attachment.txt",
            payload,
            content_type="text/plain",
        )
        response = self.api.post(
            f"/api/job/jobs/{self.job.id}/files/",
            {"files": [file_obj]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        uploaded = response.data["uploaded"][0]
        self.assertEqual(uploaded["filename"], "attachment.txt")
        self.assertEqual(uploaded["mime_type"], "text/plain")
        self.assertEqual(uploaded["size"], len(payload))
        self.assertEqual(uploaded["status"], "active")
        self.assertTrue(uploaded["download_url"])
        self.assertIn("uploaded_at", uploaded)
        self.assertIn("thumbnail_url", uploaded)

        list_response = self.api.get(f"/api/job/jobs/{self.job.id}/files/")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data[0]["id"], uploaded["id"])

        download_response = self.api.get(uploaded["download_url"])
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(b"".join(download_response.streaming_content), payload)

    def test_upload_accepts_twenty_megabyte_attachment(self):
        payload = b"7" * (20 * 1024 * 1024)
        file_obj = SimpleUploadedFile(
            "large-attachment.txt",
            payload,
            content_type="text/plain",
        )

        response = self.api.post(
            f"/api/job/jobs/{self.job.id}/files/",
            {"files": [file_obj]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        uploaded = response.data["uploaded"][0]
        self.assertEqual(uploaded["filename"], "large-attachment.txt")
        self.assertEqual(uploaded["size"], len(payload))
