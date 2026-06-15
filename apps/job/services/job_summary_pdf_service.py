"""Persist workshop PDFs as disaster-recovery job summaries."""

import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.job.helpers import get_job_folder_path
from apps.job.models import Job, JobFile
from apps.job.services.workshop_pdf_service import (
    JOB_SUMMARY_PDF_FILENAME,
    create_workshop_pdf,
)

logger = logging.getLogger(__name__)


class JobSummaryPdfService:
    """Write the canonical workshop PDF into the job's local Dropbox folder."""

    @staticmethod
    def refresh(job_id: UUID | str) -> None:
        job = Job.objects.get(id=job_id)
        if not job.job_number:
            raise ValueError(f"Job {job.id} has no job_number")

        JobSummaryPdfService._ensure_summary_not_printed(job)
        pdf_buffer = create_workshop_pdf(job)
        pdf_buffer.seek(0)
        pdf_content = pdf_buffer.read()
        if not pdf_content:
            raise ValueError("Generated job summary PDF is empty")

        target_path = JobSummaryPdfService._write_pdf(job, pdf_content)
        relative_path = os.path.relpath(target_path, settings.DROPBOX_WORKFLOW_FOLDER)

        with transaction.atomic():
            JobSummaryPdfService._upsert_job_file(job, relative_path)

        logger.info(
            "Refreshed %s for job %s at %s",
            JOB_SUMMARY_PDF_FILENAME,
            job.job_number,
            target_path,
        )

    @staticmethod
    def refresh_stale(limit: int) -> tuple[int, bool]:
        if limit < 1:
            raise ValueError("Job summary PDF reconcile limit must be positive")

        job_ids = list(
            JobSummaryPdfService._stale_jobs().values_list("id", flat=True)[: limit + 1]
        )
        for job_id in job_ids[:limit]:
            JobSummaryPdfService.refresh(job_id)

        return min(len(job_ids), limit), len(job_ids) > limit

    @staticmethod
    def _stale_jobs() -> QuerySet[Job]:
        summary_job_ids = JobFile.objects.filter(
            filename=JOB_SUMMARY_PDF_FILENAME,
            status="active",
        ).values("job_id")
        stale_job_ids = JobFile.objects.filter(
            filename=JOB_SUMMARY_PDF_FILENAME,
            status="active",
            uploaded_at__lt=F("job__updated_at"),
        ).values("job_id")
        return Job.objects.filter(
            Q(id__in=stale_job_ids) | ~Q(id__in=summary_job_ids)
        ).order_by("-updated_at")

    @staticmethod
    def _upsert_job_file(job: Job, relative_path: str) -> JobFile:
        job_file = (
            JobFile.objects.filter(job=job, filename=JOB_SUMMARY_PDF_FILENAME)
            .order_by("-uploaded_at")
            .first()
        )
        if job_file is None:
            job_file = JobFile.objects.create(
                job=job,
                filename=JOB_SUMMARY_PDF_FILENAME,
                file_path=relative_path,
                mime_type="application/pdf",
                print_on_jobsheet=False,
                status="active",
            )
        else:
            job_file.file_path = relative_path
            job_file.mime_type = "application/pdf"
            job_file.print_on_jobsheet = False
            job_file.status = "active"
            job_file.save(
                update_fields=[
                    "file_path",
                    "mime_type",
                    "print_on_jobsheet",
                    "status",
                ]
            )

        JobFile.objects.filter(pk=job_file.pk).update(uploaded_at=timezone.now())
        job_file.refresh_from_db(fields=["uploaded_at"])
        return job_file

    @staticmethod
    def _ensure_summary_not_printed(job: Job) -> None:
        JobFile.objects.filter(
            job=job,
            filename=JOB_SUMMARY_PDF_FILENAME,
            print_on_jobsheet=True,
        ).update(print_on_jobsheet=False)

    @staticmethod
    def _write_pdf(job: Job, pdf_content: bytes) -> str:
        job_folder = Path(get_job_folder_path(str(job.job_number)))
        job_folder.mkdir(parents=True, exist_ok=True)

        target_path = job_folder / JOB_SUMMARY_PDF_FILENAME
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{JOB_SUMMARY_PDF_FILENAME}.",
            suffix=".tmp",
            dir=job_folder,
        )
        try:
            with os.fdopen(fd, "wb") as destination:
                destination.write(pdf_content)
            os.chmod(tmp_path, 0o664)
            os.replace(tmp_path, target_path)
            return str(target_path)
        except Exception:
            os.unlink(tmp_path)
            raise
