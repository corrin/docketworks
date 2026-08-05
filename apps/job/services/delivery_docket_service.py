"""Delivery docket generation with persistent storage."""

import logging
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.models import Job, JobEvent, JobFile
from apps.job.services.workshop_pdf_service import create_delivery_docket_pdf

logger = logging.getLogger(__name__)


def generate_delivery_docket(job: Job, staff: Staff) -> tuple[BytesIO, JobFile]:
    """Generate a delivery docket PDF for a job and save it as a JobFile.

    Creates a PDF similar to the workshop sheet but without the materials
    notes section and with a "DELIVERY DOCKET" header. Saves it to the local
    workflow folder and creates a JobEvent to track the generation.

    ``staff`` is the Staff who triggered the print — recorded on the JobEvent
    for audit attribution (JobEvent.staff is NOT NULL).

    Returns the PDF buffer for immediate download and the saved JobFile.
    """
    if not job.job_number:
        raise ValueError("Job must have a job_number to generate delivery docket")

    try:
        # Generate the PDF as a delivery docket (no materials table, with prefix)
        pdf_buffer = create_delivery_docket_pdf(job)

        # Read the buffer content for saving
        pdf_content = pdf_buffer.read()
        pdf_buffer.seek(0)  # Reset for return

        # Generate unique filename
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        filename = f"delivery_docket_{job.job_number}_{timestamp}.pdf"

        # Define the job folder path (same as the upload endpoint)
        job_folder = Path(settings.DROPBOX_WORKFLOW_FOLDER) / f"Job-{job.job_number}"
        job_folder.mkdir(parents=True, exist_ok=True)

        # Save PDF to disk
        file_path = job_folder / filename
        file_path.write_bytes(pdf_content)
        file_path.chmod(0o664)

        # Create JobFile instance (path relative to the workflow folder)
        job_file = JobFile.objects.create(
            job=job,
            filename=filename,
            file_path=f"Job-{job.job_number}/{filename}",
            mime_type="application/pdf",
            print_on_jobsheet=False,  # Delivery dockets shouldn't print on job sheets
            status="active",
        )

        # Create JobEvent to track generation
        JobEvent.objects.create(
            job=job,
            staff=staff,
            event_type="delivery_docket_generated",
            detail={
                "filename": filename,
                "file_id": str(job_file.id),
            },
        )

        logger.info("Delivery docket generated for job %s: %s", job.job_number, filename)
    except Exception as exc:
        logger.exception("Failed to generate delivery docket for job %s", job.job_number)
        persist_app_error(exc, AppErrorContext(job_id=str(job.id)))
        raise

    return pdf_buffer, job_file
