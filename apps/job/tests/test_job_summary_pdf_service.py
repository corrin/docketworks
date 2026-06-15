import shutil
import tempfile
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from django.core.cache import caches
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.client.models import Client
from apps.job.models import CostLine, Job, JobFile
from apps.job.services.job_summary_pdf_service import JobSummaryPdfService
from apps.job.services.workshop_pdf_service import JOB_SUMMARY_PDF_FILENAME
from apps.job.tasks import (
    JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY,
    refresh_job_summary_pdfs_task,
    request_job_summary_pdf_refresh,
)
from apps.testing import BaseTestCase
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import AppError


class JobSummaryPdfServiceTests(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.dropbox = tempfile.mkdtemp(prefix="dw-summary-pdf-")
        self.settings_override = override_settings(DROPBOX_WORKFLOW_FOLDER=self.dropbox)
        self.settings_override.enable()
        self.client_obj = Client.objects.create(
            name="Summary Client",
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            client=self.client_obj,
            name="Summary Job",
            staff=self.test_staff,
        )
        caches["shared"].clear()

    def tearDown(self) -> None:
        caches["shared"].clear()
        self.settings_override.disable()
        shutil.rmtree(self.dropbox, ignore_errors=True)
        super().tearDown()

    def test_refresh_writes_stable_pdf_and_job_file(self) -> None:
        with patch(
            "apps.job.services.job_summary_pdf_service.create_workshop_pdf",
            return_value=BytesIO(b"%PDF first"),
        ):
            JobSummaryPdfService.refresh(self.job.id)

        path = Path(self.dropbox) / f"Job-{self.job.job_number}" / "JobSummary.pdf"
        job_file = JobFile.objects.get(job=self.job, filename=JOB_SUMMARY_PDF_FILENAME)
        self.assertEqual(path.read_bytes(), b"%PDF first")
        self.assertEqual(
            job_file.file_path, f"Job-{self.job.job_number}/JobSummary.pdf"
        )
        self.assertEqual(job_file.mime_type, "application/pdf")
        self.assertFalse(job_file.print_on_jobsheet)

    def test_refresh_batches_missing_jobs_and_skips_fresh(self) -> None:
        missing = Job.objects.create(
            client=self.client_obj,
            name="Missing Summary",
            staff=self.test_staff,
        )
        fresh = Job.objects.create(
            client=self.client_obj,
            name="Fresh Summary",
            staff=self.test_staff,
        )
        JobFile.objects.create(
            job=fresh,
            filename=JOB_SUMMARY_PDF_FILENAME,
            file_path=f"Job-{fresh.job_number}/JobSummary.pdf",
            mime_type="application/pdf",
            print_on_jobsheet=False,
            status="active",
        )
        refreshed: list[UUID] = []

        with patch.object(
            JobSummaryPdfService, "refresh", side_effect=refreshed.append
        ):
            refreshed_count, remaining = JobSummaryPdfService.refresh_stale(limit=1)

        self.assertEqual(refreshed_count, 1)
        self.assertTrue(remaining)
        self.assertTrue(set(refreshed).issubset({self.job.id, missing.id}))

    def test_central_save_paths_poke_one_reconciler(self) -> None:
        with patch("apps.job.tasks.refresh_job_summary_pdfs_task") as task:
            with self.captureOnCommitCallbacks(execute=True):
                self.job.name = "Renamed"
                self.job.save(staff=self.test_staff, update_fields=["name"])
                CostLine.objects.create(
                    cost_set=self.job.latest_actual,
                    kind="adjust",
                    desc="Workshop adjustment",
                    quantity=Decimal("1.00"),
                    unit_cost=Decimal("0.00"),
                    unit_rev=Decimal("0.00"),
                    accounting_date=timezone.localdate(),
                    meta={"comments": "summary PDF poke"},
                )

        self.assertEqual(task.apply_async.call_count, 1)


class JobSummaryPdfTaskTests(TestCase):
    def tearDown(self) -> None:
        caches["shared"].clear()

    def test_request_refresh_debounces_dispatch(self) -> None:
        caches["shared"].clear()
        with patch("apps.job.tasks.refresh_job_summary_pdfs_task") as task:
            with self.captureOnCommitCallbacks(execute=True):
                request_job_summary_pdf_refresh()
                request_job_summary_pdf_refresh()

        self.assertEqual(task.apply_async.call_count, 1)
        self.assertTrue(caches["shared"].get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY))

    def test_refresh_task_persists_failure_once(self) -> None:
        before = AppError.objects.count()
        with patch(
            "apps.job.services.job_summary_pdf_service.JobSummaryPdfService.refresh_stale",
            side_effect=RuntimeError("summary render failed"),
        ):
            with self.assertRaises(AlreadyLoggedException):
                refresh_job_summary_pdfs_task()

        self.assertEqual(AppError.objects.count(), before + 1)
