"""Service for generating delivery dockets with persistent storage."""

import logging
import os
from io import BytesIO

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job, JobEvent, JobFile
from apps.job.services.workshop_pdf_service import create_delivery_docket_pdf
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger(__name__)


def generate_delivery_docket(job: Job, staff: Staff) -> tuple[BytesIO, JobFile]:
    """
    Generate a delivery docket PDF for a job and save it as a JobFile.

    Creates a PDF similar to the workshop sheet but without the materials notes
    section and with "DELIVERY DOCKET" header. Saves it to the Dropbox workflow
    folder and creates a JobEvent to track the generation.

    Args:
        job: The Job instance to generate the delivery docket for
        staff: The Staff who triggered the print — recorded on the JobEvent
            for audit attribution. Required since migration 0079 made
            JobEvent.staff NOT NULL.

    Returns:
        tuple containing:
            - BytesIO: The PDF buffer for immediate download
            - JobFile: The saved JobFile instance

    Raises:
        Exception: If PDF generation or file saving fails
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

        # Define the job folder path (same as upload view)
        job_folder = os.path.join(
            settings.DROPBOX_WORKFLOW_FOLDER, f"Job-{job.job_number}"
        )
        os.makedirs(job_folder, exist_ok=True)

        # Save PDF to disk
        file_path = os.path.join(job_folder, filename)
        with open(file_path, "wb") as destination:
            destination.write(pdf_content)
        os.chmod(file_path, 0o664)

        # Create relative path for database
        relative_path = os.path.relpath(file_path, settings.DROPBOX_WORKFLOW_FOLDER)

        # Create JobFile instance
        job_file = JobFile.objects.create(
            job=job,
            filename=filename,
            file_path=relative_path,
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

        logger.info(f"Delivery docket generated for job {job.job_number}: {filename}")

        return pdf_buffer, job_file

    except Exception as exc:
        logger.error(
            f"Failed to generate delivery docket for job {job.job_number}: {exc}"
        )
        try:
            persist_and_raise(exc)
        except AlreadyLoggedException:
            raise
